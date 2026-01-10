import os
import json
import pandas as pd
from dataclasses import dataclass
from rich.console import Console

from src.pricing.jupiter_prices import JupiterPriceClient

console = Console()

# Solana USDC mint (mainnet)
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@dataclass
class SimConfig:
    starting_cash: float = 1000.0
    copy_fraction: float = 0.10      # follower copies 10% of leader size
    fee_bps: float = 20.0            # 0.20% fee
    slippage_bps: float = 30.0       # 0.30% slippage
    delay_seconds: int = 30          # execution delay (placeholder for now)
    min_trade: float = 0.01          # ignore dust trades


def bps_to_mult(bps: float) -> float:
    return bps / 10_000.0


def resolve_price_usd(mint: str, price_client: JupiterPriceClient) -> float | None:
    """
    Resolve a USD spot price for a mint.
    - USDC hardcoded to 1.0
    - otherwise Jupiter price (may be None)
    """
    if not mint:
        return None
    if mint == USDC_MINT:
        return 1.0
    return price_client.get_price(mint)


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
    position = 0.0  # token units (simplified single-asset position for demo)
    equity_curve = []

    price_client = JupiterPriceClient()
    last_price = 1.0  # fallback for equity marking if needed

    for _, row in leader.iterrows():
        t = row.get("block_time")
        mint = row.get("mint")
        leader_size = float(row.get("ui_amount", 0.0))

        # Ignore very small transfers
        if leader_size < cfg.min_trade:
            continue

        # Resolve USD price (USDC fallback -> 1.0)
        price = resolve_price_usd(mint, price_client)

        # If price unavailable, skip (keeps results honest)
        if price is None:
            equity_curve.append(
                {
                    "t": t,
                    "event": "skip_no_price",
                    "mint": mint,
                    "cash": cash,
                    "position": position,
                    "price": last_price,
                    "equity": cash + position * last_price,
                }
            )
            continue

        last_price = price

        # Follower trade size (token units)
        trade_size = leader_size * cfg.copy_fraction

        # Apply slippage and fees as cost multipliers (token units)
        trade_cost_tokens = trade_size * (1.0 + fee_mult + slip_mult)

        # Convert cost to USD using price
        trade_cost_usd = trade_cost_tokens * price

        if trade_cost_usd > cash:
            equity_curve.append(
                {
                    "t": t,
                    "event": "skip_insufficient_cash",
                    "mint": mint,
                    "cash": cash,
                    "position": position,
                    "price": price,
                    "equity": cash + position * price,
                }
            )
            continue

        # Execute "buy"
        cash -= trade_cost_usd
        position += trade_size

        equity_curve.append(
            {
                "t": t,
                "event": "copy_buy",
                "mint": mint,
                "cash": cash,
                "position": position,
                "price": price,
                "equity": cash + position * price,
            }
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
        "skipped_no_price": int((curve["event"] == "skip_no_price").sum()),
        "skipped_insufficient_cash": int((curve["event"] == "skip_insufficient_cash").sum()),
        "copy_fraction": cfg.copy_fraction,
        "fee_bps": cfg.fee_bps,
        "slippage_bps": cfg.slippage_bps,
        "delay_seconds": cfg.delay_seconds,
    }

    out_curve = "artifacts/copytrade_equity_curve.csv"
    out_summary = "artifacts/copytrade_summary.json"

    curve.to_csv(out_curve, index=False)

    with open(out_summary, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    console.print(f"[green]Saved[/green] {out_curve}")
    console.print(f"[green]Saved[/green] {out_summary}")
    console.print(summary)


if __name__ == "__main__":
    main()
