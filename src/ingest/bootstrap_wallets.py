import json
from collections import Counter
from typing import Any, Dict, List, Optional

from configs.settings import get_settings
from src.ingest.solana_rpc import RpcClient

# Solana USDC mint (widely used, high activity)
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def extract_signers(tx: Dict[str, Any]) -> List[str]:
    """
    Extract signer pubkeys from a getTransaction(jsonParsed) response.
    """
    signers: List[str] = []
    tx_obj = tx.get("transaction", {})
    msg = tx_obj.get("message", {})
    keys = msg.get("accountKeys", [])

    # In jsonParsed, accountKeys is typically a list of dicts: {pubkey, signer, writable}
    for k in keys:
        if isinstance(k, dict):
            if k.get("signer") is True:
                pk = k.get("pubkey")
                if pk:
                    signers.append(pk)
        # fallback: sometimes it's a list of strings (older encoding)
        elif isinstance(k, str):
            # can't know signer in this case, skip
            continue

    return signers


def main(limit_signatures: int = 100, sample_txs: int = 40) -> None:
    s = get_settings()
    client = RpcClient(rpc_url=s.solana_rpc)

    sigs = client.get_signatures_for_address(USDC_MINT, limit=limit_signatures)
    signatures = [x.get("signature") for x in sigs if x.get("signature")]

    print(f"USDC mint signatures fetched: {len(signatures)}")
    if not signatures:
        print("No signatures returned. Try increasing limit or re-check RPC.")
        return

    # Sample the first N transactions and collect signer wallets
    counts: Counter[str] = Counter()
    sampled = 0

    for sig in signatures:
        tx = client.get_transaction(sig)
        if tx is None:
            continue

        for signer in extract_signers(tx):
            counts[signer] += 1

        sampled += 1
        if sampled >= sample_txs:
            break

    top = counts.most_common(15)
    out = {
        "source": "USDC mint signer sampling",
        "limit_signatures": limit_signatures,
        "sample_txs": sample_txs,
        "top_signers": top,
    }

    with open("artifacts/candidate_wallets.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print("\nTop active signer wallets (candidates):")
    for i, (addr, c) in enumerate(top[:10], start=1):
        print(f"{i:>2}. {addr}  (seen {c} times)")

    if len(top) >= 2:
        print("\nSuggested:")
        print(f"WALLET_A={top[0][0]}")
        print(f"WALLET_B={top[1][0]}")
        print("\nSaved artifacts/candidate_wallets.json")


if __name__ == "__main__":
    main()
