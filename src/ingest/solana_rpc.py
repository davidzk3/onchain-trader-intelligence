import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from rich.console import Console

console = Console()


@dataclass
class RpcClient:
    rpc_url: str
    timeout_s: float = 30.0
    max_retries: int = 3

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout_s) as client:
                    r = client.post(self.rpc_url, json=payload)
                    r.raise_for_status()
                    data = r.json()
                    if "error" in data:
                        raise RuntimeError(f"RPC error: {data['error']}")
                    return data
            except Exception as e:
                last_err = e
                console.print(f"[yellow]RPC attempt {attempt}/{self.max_retries} failed:[/yellow] {e}")
                time.sleep(1.2 * attempt)

        raise RuntimeError(f"RPC failed after retries: {last_err}")

    def get_signatures_for_address(self, address: str, limit: int = 50) -> List[Dict[str, Any]]:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [address, {"limit": limit}],
        }
        return self._post(payload).get("result", [])

    def get_transaction(self, signature: str) -> Optional[Dict[str, Any]]:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [
                signature,
                {
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        }
        return self._post(payload).get("result", None)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def save_json(path: str, obj: Any) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def fetch_wallet_transactions(rpc_url: str, wallet: str, limit: int = 30) -> Dict[str, Any]:
    """
    Fetch recent tx signatures for a wallet and then pull full transaction details.
    Returns a dict you can store.
    """
    client = RpcClient(rpc_url=rpc_url)
    sigs = client.get_signatures_for_address(wallet, limit=limit)

    signatures = [s["signature"] for s in sigs if "signature" in s]
    console.print(f"[cyan]{wallet}[/cyan] signatures fetched: {len(signatures)}")

    txs: List[Dict[str, Any]] = []
    for i, sig in enumerate(signatures, start=1):
        try:
            tx = client.get_transaction(sig)
            if tx is not None:
                txs.append({"signature": sig, "tx": tx})
            console.print(f"  fetched {i}/{len(signatures)}", end="\r")
        except Exception as e:
            console.print(f"[red]Failed tx {sig}[/red]: {e}")

        time.sleep(0.15)

    console.print("")
    return {
        "wallet": wallet,
        "limit": limit,
        "signature_count": len(signatures),
        "tx_count": len(txs),
        "items": txs,
    }


def fetch_tx_by_signature(rpc_url: str, signature: str) -> Optional[Dict[str, Any]]:
    """
    Convenience helper used by realtime/watch_wallet.
    Returns the tx (jsonParsed) or None if not found.
    """
    client = RpcClient(rpc_url=rpc_url)
    return client.get_transaction(signature)
