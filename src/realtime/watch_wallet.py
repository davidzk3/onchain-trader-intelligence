# src/realtime/watch_wallet.py

import os
import json
import asyncio
import time
from pathlib import Path
from typing import Dict, List, Tuple

import websockets
from rich.console import Console
from dotenv import load_dotenv

from src.ingest.solana_rpc import fetch_tx_by_signature
from src.ingest.extract_transfers import extract_spl_transfers_from_tx

console = Console()

OUT_PATH = Path("artifacts/realtime_signals.jsonl")
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

WRITE_LOCK = asyncio.Lock()


async def write_signal(payload: dict) -> None:
    payload["_ts"] = time.time()
    line = json.dumps(payload, ensure_ascii=False)
    async with WRITE_LOCK:
        with OUT_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def infer_from_transfers(transfers: List[dict]) -> dict:
    """
    Realtime inference:
    - pick top transfer by absolute amount
    - compute dominance = top / total
    - classify by top_amount thresholds
    """
    if not transfers:
        return {"signal": "no_transfers"}

    cleaned: List[Tuple[str, float]] = []
    for t in transfers:
        mint = t.get("mint")
        if not mint:
            continue
        amt = abs(float(t.get("ui_amount", 0) or 0))
        cleaned.append((mint, amt))

    if not cleaned:
        return {"signal": "no_transfers"}

    total = sum(a for _, a in cleaned)
    top_mint, top_amt = max(cleaned, key=lambda x: x[1])
    dominance = (top_amt / total) if total > 0 else 0.0

    if top_amt >= 10:
        label = "whale_activity"
    elif top_amt >= 1:
        label = "large_transfer"
    else:
        label = "normal_transfer"

    return {
        "signal": label,
        "transfer_count": len(cleaned),
        "top_mint": top_mint,
        "top_amount": top_amt,
        "total_amount": total,
        "dominance": dominance,
    }


def load_wallets_from_env() -> Dict[str, str]:
    wallets: Dict[str, str] = {}
    for label in ("A", "B", "C"):
        v = (os.getenv(f"WALLET_{label}") or "").strip()
        if v:
            wallets[label] = v
    return wallets


def resolve_watch_set(wallets: Dict[str, str]) -> Dict[str, str]:
    """
    WATCH_LABEL behavior:
    - unset: watch all wallets found (A/B/C)
    - set to 'A'/'B'/'C': watch that env wallet only
    - set to address: watch only that address
      (if it matches WALLET_A/B/C, keep that label; otherwise label as 'X')
    """
    watch_label = (os.getenv("WATCH_LABEL") or "").strip()

    if not watch_label:
        return wallets

    upper = watch_label.upper()

    # If user provided a label like A/B/C
    if upper in wallets:
        return {upper: wallets[upper]}

    # Otherwise treat it as an address
    addr = watch_label

    # Try to map to existing A/B/C if it matches
    for lbl, a in wallets.items():
        if a == addr:
            return {lbl: addr}

    # Not found in A/B/C — still watch it
    return {"X": addr}


async def watch_one_wallet(
    *,
    wallet_label: str,
    wallet_addr: str,
    ws_url: str,
    rpc_url: str,
) -> None:
    backoff_s = 1.0

    while True:
        try:
            console.print(f"[cyan]({wallet_label}) Connecting WS[/cyan] {ws_url}")

            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                sub = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "logsSubscribe",
                    "params": [{"mentions": [wallet_addr]}, {"commitment": "finalized"}],
                }

                await ws.send(json.dumps(sub))
                resp = await ws.recv()
                console.print(f"[green]({wallet_label}) Subscribed[/green] {resp}")

                backoff_s = 1.0

                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)

                    if data.get("method") != "logsNotification":
                        continue

                    val = data["params"]["result"]["value"]
                    sig = val.get("signature")
                    err = val.get("err")

                    event = {
                        "wallet_label": wallet_label,
                        "wallet": wallet_addr,
                        "signature": sig,
                        "err": err,
                    }

                    if sig and err is None:
                        try:
                            tx = fetch_tx_by_signature(rpc_url=rpc_url, signature=sig)
                            if tx is None:
                                event["signal"] = "tx_missing"
                            else:
                                transfers = extract_spl_transfers_from_tx(
                                    wallet_label=wallet_label,
                                    signature=sig,
                                    tx=tx,
                                )
                                inf = infer_from_transfers([t.__dict__ for t in transfers])
                                event.update(inf)
                        except Exception as e:
                            event["signal"] = "fetch_failed"
                            event["error"] = str(e)

                    await write_signal(event)
                    console.print(event)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            console.print(f"[yellow]({wallet_label}) WS error, reconnecting:[/yellow] {e}")

        await asyncio.sleep(backoff_s)
        backoff_s = min(backoff_s * 1.7, 30.0)


async def main() -> None:
    load_dotenv(override=True)

    ws_url = (os.getenv("SOLANA_WS") or "").strip()
    rpc_url = (os.getenv("SOLANA_RPC") or "").strip()

    if not ws_url:
        raise ValueError("SOLANA_WS missing from .env")
    if not rpc_url:
        raise ValueError("SOLANA_RPC missing from .env")

    wallets_all = load_wallets_from_env()
    if not wallets_all:
        raise ValueError("No wallets found. Set WALLET_A / WALLET_B / WALLET_C in .env")

    wallets = resolve_watch_set(wallets_all)

    console.print(
        {
            "watching": wallets,
            "ws": ws_url,
            "rpc": rpc_url,
            "out": str(OUT_PATH),
            "watch_label_env": (os.getenv("WATCH_LABEL") or "").strip(),
        }
    )

    tasks = [
        asyncio.create_task(
            watch_one_wallet(
                wallet_label=label,
                wallet_addr=addr,
                ws_url=ws_url,
                rpc_url=rpc_url,
            )
        )
        for label, addr in wallets.items()
    ]

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/yellow]")
