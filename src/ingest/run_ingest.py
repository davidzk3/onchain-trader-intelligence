import datetime as dt

from configs.settings import get_settings
from src.ingest.solana_rpc import fetch_wallet_transactions, save_json


def main() -> None:
    s = get_settings()
    stamp = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    for label, wallet in [("A", s.wallet_a), ("B", s.wallet_b)]:
        data = fetch_wallet_transactions(s.solana_rpc, wallet, limit=30)
        out_path = f"data/raw/wallet_{label}_tx_{stamp}.json"
        save_json(out_path, data)
        print(f"Saved: {out_path} (txs={data['tx_count']})")


if __name__ == "__main__":
    main()
