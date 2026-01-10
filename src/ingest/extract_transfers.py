import glob
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from rich.console import Console

console = Console()


@dataclass
class Transfer:
    wallet_label: str
    signature: str
    block_time: Optional[int]
    mint: str
    source: Optional[str]
    destination: Optional[str]
    amount: Optional[float]
    decimals: Optional[int]
    ui_amount: Optional[float]
    program: str  # "spl-token" or other label


def safe_get(d: Dict[str, Any], path: List[str]) -> Any:
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def extract_spl_transfers_from_tx(wallet_label: str, signature: str, tx: Dict[str, Any]) -> List[Transfer]:
    """
    Extract SPL token transfers from a Solana getTransaction(jsonParsed) payload.

    We look at:
      meta.preTokenBalances / meta.postTokenBalances (for changes)
      parsed instructions that are token transfers
    For now, we prioritize parsed token transfer instructions because they contain
    source/destination/mint/uiAmount when available.
    """
    out: List[Transfer] = []

    block_time = tx.get("blockTime")
    tx_obj = tx.get("transaction", {})
    msg = tx_obj.get("message", {})

    instructions = msg.get("instructions", []) or []

    for ix in instructions:
        # jsonParsed format: { "program": "...", "parsed": { "type": "...", "info": {...}}}
        program = ix.get("program")
        parsed = ix.get("parsed")

        if program not in ("spl-token", "token"):
            continue
        if not isinstance(parsed, dict):
            continue

        ix_type = parsed.get("type")
        info = parsed.get("info", {})

        # common types: "transfer", "transferChecked"
        if ix_type not in ("transfer", "transferChecked"):
            continue

        mint = info.get("mint")
        source = info.get("source")
        destination = info.get("destination")

        # Different shapes depending on transfer vs transferChecked
        decimals = info.get("decimals")
        token_amount = info.get("tokenAmount")  # sometimes present
        amount = None
        ui_amount = None

        if isinstance(token_amount, dict):
            # tokenAmount: { "amount": "123", "decimals": 6, "uiAmount": 0.000123, "uiAmountString": "..." }
            decimals = token_amount.get("decimals", decimals)
            ui_amount = token_amount.get("uiAmount")
            # amount is raw integer; we won't force convert if not needed
            raw_amt = token_amount.get("amount")
            try:
                if raw_amt is not None:
                    amount = float(raw_amt)
            except Exception:
                amount = None
        else:
            # sometimes "amount" exists directly as string
            raw_amt = info.get("amount")
            try:
                if raw_amt is not None:
                    amount = float(raw_amt)
            except Exception:
                amount = None

            # if we have decimals, we can compute ui_amount
            if amount is not None and isinstance(decimals, int):
                ui_amount = amount / (10 ** decimals)

        if not mint:
            # Some parsed transfers omit mint; we can try to infer later.
            # For now skip mint-less transfers to keep dataset clean.
            continue

        out.append(
            Transfer(
                wallet_label=wallet_label,
                signature=signature,
                block_time=block_time,
                mint=mint,
                source=source,
                destination=destination,
                amount=amount,
                decimals=decimals if isinstance(decimals, int) else None,
                ui_amount=ui_amount,
                program="spl-token",
            )
        )

    return out


def load_latest_wallet_files() -> List[Tuple[str, str]]:
    """
    Returns list of (wallet_label, filepath) for the latest A and B json dumps.
    """
    a_files = sorted(glob.glob("data/raw/wallet_A_tx_*.json"))
    b_files = sorted(glob.glob("data/raw/wallet_B_tx_*.json"))

    if not a_files or not b_files:
        raise FileNotFoundError("Could not find data/raw/wallet_A_tx_*.json or wallet_B_tx_*.json. Run ingest first.")

    return [("A", a_files[-1]), ("B", b_files[-1])]


def main() -> None:
    files = load_latest_wallet_files()
    transfers: List[Transfer] = []

    for wallet_label, path in files:
        console.print(f"[cyan]Reading[/cyan] {path}")
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        items = payload.get("items", [])
        for item in items:
            signature = item.get("signature")
            tx = item.get("tx")
            if not signature or not isinstance(tx, dict):
                continue

            transfers.extend(extract_spl_transfers_from_tx(wallet_label, signature, tx))

    if not transfers:
        console.print("[yellow]No SPL transfers found in these transactions.[/yellow]")
    else:
        console.print(f"[green]Extracted transfers:[/green] {len(transfers)}")

    # Convert to DataFrame
    df = pd.DataFrame([t.__dict__ for t in transfers])

    os.makedirs("data/processed", exist_ok=True)
    out_csv = "data/processed/transfers.csv"
    df.to_csv(out_csv, index=False)
    console.print(f"[green]Saved[/green] {out_csv}")

    # Also save a quick summary for sanity
    if not df.empty:
        summary = (
            df.groupby(["wallet_label", "mint"])
              .agg(tx_count=("signature", "nunique"), total_ui=("ui_amount", "sum"))
              .reset_index()
              .sort_values(["wallet_label", "tx_count"], ascending=[True, False])
        )
        out_sum = "artifacts/transfer_summary.csv"
        os.makedirs("artifacts", exist_ok=True)
        summary.to_csv(out_sum, index=False)
        console.print(f"[green]Saved[/green] {out_sum}")


if __name__ == "__main__":
    main()
