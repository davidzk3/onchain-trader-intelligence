import os
import pandas as pd
import numpy as np
from dataclasses import dataclass
from rich.console import Console

console = Console()


@dataclass
class SimConfig:
    starting_cash: float = 1000.0
    copy_fraction: float = 0.10      # follower copies 10% of leader size
    fee_bps: float = 20.0            # 0.20% fee
    slippage_bps: float = 30.0       # 0.30% slippage
    delay_seconds: int = 30          # execution delay
    min_trade: float = 0.01          # ignore dust trades


def bps_to_mult(bps: float) -> float:
    return bps / 10_000.0


def main():
    os.makedirs("artifacts", exist_ok=True)

    df = pd.read_csv("data/processed/transfers.csv")
    if df.empty:
        raise ValueError("transfers.csv is empty. Run extract_transfers first.")

    # Clean columns
    df["block_time"] = pd.to_numeric(df["block_time"], errors="coerce")
    df["ui_amount"] = pd.to_numeric(df["ui_amount"], errors="coerce").fillna(0.0)

    # Filter to leader wallet transfers only (A)
    leader = df[df["wallet_label"] == "A"].copy()
    if leader.empty:
        raise ValueError("No leader transfers found for wallet_label == 'A'")

    # Sort by time (oldest -> newest)
    leader = leader.sort_values("block_time", na_position="last").reset_index(drop=True)

    cfg = SimConfig()

    fee_mult = bps_to_mult(cfg.fee_bps)
    slip_mult = bps_to_mult(cfg.slippage_bps)

    cash = cfg.starting_cash
    position = 0.0  # "token units" position placeholder
    equity_curve = []

    # We don't have real prices here. We'll simulate a naive "impact" model:
    # - treat each transfer as a "buy signal"
    # - price proxy drifts randomly, just to produce an equity curve
    rng = np.random.default_rng(42)
    price = 1.0

    for i, row in leader.iterrows():
        t = row.get("block_time")
        mint = row.get("mint")
        leader_size = float(row.get("ui_amount", 0.0))

        # Ignore very small transfers
        if leader_size < cfg.min_trade:
            continue

        # Follower trade size
        trade_size = leader_size * cfg.copy_fraction

        # Apply slippage and fees as cost multipliers
        trade_cost = trade_size * (1.0 + fee_mult + slip_mult)

        # Only execute if we have cash
        if trade_cost > cash:
            # skip trade
            equity_curve.append(
                {"t": t, "event": "skip_insufficient_cash", "mint": mint, "cash": cash, "position": position, "price": price,
                 "equity": cash + position * price}
            )
            continue

        # Execute "buy"
        cash -= trade_cost
        position += trade_size

        # Update price proxy (random walk)
        price *= float(np.clip(1.0 + rng.normal(0, 0.01), 0.95, 1.05))

        equity_curve.append(
            {"t": t, "event": "copy_buy", "mint": mint, "cash": cash, "position": position, "price": price,
             "equity": cash + position * price}
        )

    curve = pd.DataFrame(equity_curve)
    if curve.empty:
        raise ValueError("No simulated trades executed. Try lowering min_trade or copy_fraction.")

    # Metrics
    curve["equity_return"] = curve["equity"].pct_change().fillna(0.0)
    total_return = (curve["equity"].iloc[-1] / cfg.starting_cash) - 1.0
    max_drawdown = ((curve["equity"] / curve["equity"].cummax()) - 1.0).min()

    summary = {
        "starting_cash": cfg.starting_cash,
        "ending_equity": float(curve["equity"].iloc[-1]),
        "total_return_pct": float(total_return * 100.0),
        "max_drawdown_pct": float(max_drawdown * 100.0),
        "trades_executed": int((curve["event"] == "copy_buy").sum()),
        "trades_skipped": int((curve["event"] != "copy_buy").sum()),
        "copy_fraction": cfg.copy_fraction,
        "fee_bps": cfg.fee_bps,
        "slippage_bps": cfg.slippage_bps,
        "delay_seconds": cfg.delay_seconds,
    }

    out_curve = "artifacts/copytrade_equity_curve.csv"
    out_summary = "artifacts/copytrade_summary.json"

    curve.to_csv(out_curve, index=False)

    import json
    with open(out_summary, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    console.print(f"[green]Saved[/green] {out_curve}")
    console.print(f"[green]Saved[/green] {out_summary}")
    console.print(summary)


if __name__ == "__main__":
    main()
