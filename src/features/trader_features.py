import pandas as pd
import numpy as np
from rich.console import Console

console = Console()


def build_trader_features(transfers_csv: str = "data/processed/transfers.csv") -> pd.DataFrame:
    df = pd.read_csv(transfers_csv)

    if df.empty:
        raise ValueError("Transfers CSV is empty")

    # Basic cleaning
    df["ui_amount"] = pd.to_numeric(df["ui_amount"], errors="coerce").fillna(0.0)

    # Trader-level aggregates
    features = (
        df.groupby("wallet_label")
        .agg(
            transfer_count=("signature", "nunique"),
            total_volume=("ui_amount", "sum"),
            avg_transfer_size=("ui_amount", "mean"),
            median_transfer_size=("ui_amount", "median"),
            unique_tokens=("mint", "nunique"),
            max_transfer=("ui_amount", "max"),
        )
        .reset_index()
    )

    # Simple behavioral ratios
    features["avg_vs_max_ratio"] = (
        features["avg_transfer_size"] / features["max_transfer"].replace(0, np.nan)
    ).fillna(0.0)

    console.print("[green]Trader features built:[/green]")
    console.print(features)

    return features


def main():
    df = build_trader_features()

    out = "artifacts/trader_features.csv"
    df.to_csv(out, index=False)
    console.print(f"[green]Saved[/green] {out}")


if __name__ == "__main__":
    main()
