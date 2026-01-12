# src/realtime/execute_signals.py

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from rich.console import Console

from src.pricing.jupiter_prices import JupiterPriceClient

console = Console()

SIGNALS_PATH = Path("artifacts/realtime_signals.jsonl")
OUT_TRADES = Path("artifacts/paper_trades.csv")
OUT_EQUITY = Path("artifacts/paper_equity_curve.csv")


@dataclass
class ExecConfig:
    starting_cash: float = 1000.0
    copy_fraction: float = 0.10
    fee_bps: float = 20.0
    slippage_bps: float = 30.0

    min_signal_amount: float = 1.0
    min_dominance: float = 0.7

    # exits
    hold_seconds: int = 900           # time based exit
    take_profit_pct: float = 2.0      # +2%
    stop_loss_pct: float = 1.0        # -1%
    sell_fraction: float = 1.0        # sell 100% when exit triggers

    # optional allowlist for mints, comma separated in env
    allow_mints_csv: str = ""


def bps_to_mult(bps: float) -> float:
    return bps / 10_000.0


def _env_is_set(name: str) -> bool:
    v = os.getenv(name)
    return v is not None and str(v).strip() != ""


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return float(default)
    try:
        return float(v)
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return int(default)
    try:
        return int(float(v))
    except Exception:
        return int(default)


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_allowlist(cfg: ExecConfig) -> Optional[set[str]]:
    s = (cfg.allow_mints_csv or "").strip()
    if not s:
        return None
    return {x.strip() for x in s.split(",") if x.strip()}


def load_events(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Run watch_wallet first.")
    events = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def main():
    # ✅ Ensure .env is loaded from project root and overrides existing env vars
    load_dotenv(dotenv_path=Path(".env"), override=True)

    tier = (os.getenv("PAPER_TIER", "") or "").strip().upper()
    temp_lower = _env_bool("PAPER_TEMP_LOWER_THRESHOLDS", False)

    # Base config from env (or defaults)
    cfg = ExecConfig(
        starting_cash=_env_float("PAPER_STARTING_CASH", 1000.0),
        copy_fraction=_env_float("PAPER_COPY_FRACTION", 0.10),
        fee_bps=_env_float("PAPER_FEE_BPS", 20.0),
        slippage_bps=_env_float("PAPER_SLIPPAGE_BPS", 30.0),
        min_signal_amount=_env_float("PAPER_MIN_SIGNAL_AMOUNT", 1.0),
        min_dominance=_env_float("PAPER_MIN_DOMINANCE", 0.7),
        hold_seconds=_env_int("PAPER_HOLD_SECONDS", 900),
        take_profit_pct=_env_float("PAPER_TAKE_PROFIT_PCT", 2.0),
        stop_loss_pct=_env_float("PAPER_STOP_LOSS_PCT", 1.0),
        sell_fraction=_env_float("PAPER_SELL_FRACTION", 1.0),
        allow_mints_csv=os.getenv("PAPER_ALLOW_MINTS", "") or "",
    )

    # Allowed signals (default)
    allowed_signals = {"large_transfer", "whale_activity"}

    # Tier defaults (ONLY apply if user didn't explicitly set env vars)
    if tier == "LOW_RISK":
        if not _env_is_set("PAPER_COPY_FRACTION"):
            cfg.copy_fraction = 0.05
        if not _env_is_set("PAPER_MIN_DOMINANCE"):
            cfg.min_dominance = 0.85
        if not _env_is_set("PAPER_MIN_SIGNAL_AMOUNT"):
            cfg.min_signal_amount = 1.0
        if not _env_is_set("PAPER_TAKE_PROFIT_PCT"):
            cfg.take_profit_pct = 1.0
        if not _env_is_set("PAPER_STOP_LOSS_PCT"):
            cfg.stop_loss_pct = 0.5
        if not _env_is_set("PAPER_HOLD_SECONDS"):
            cfg.hold_seconds = 600

    # ✅ TEMP lowering while testing:
    # - widen allowed signals to include normal_transfer
    # - FORCE literal relaxed thresholds (do not re-read env here)
    if temp_lower:
        allowed_signals = {"normal_transfer", "large_transfer", "whale_activity"}

        # Force these down for test runs, regardless of tier defaults.
        # (If you want env to still override, remove these two lines.)
        cfg.min_signal_amount = 0.01
        cfg.min_dominance = 0.30

        # Fast testing: shorten hold unless explicitly set
        if not _env_is_set("PAPER_HOLD_SECONDS"):
            cfg.hold_seconds = min(cfg.hold_seconds, 180)

    console.print(
        {
            "tier": tier or "DEFAULT",
            "temp_lower": temp_lower,
            "allowed_signals": sorted(list(allowed_signals)),
            "min_signal_amount": cfg.min_signal_amount,
            "min_dominance": cfg.min_dominance,
            "copy_fraction": cfg.copy_fraction,
            "hold_seconds": cfg.hold_seconds,
            "tp_pct": cfg.take_profit_pct,
            "sl_pct": cfg.stop_loss_pct,
        }
    )

    allow = parse_allowlist(cfg)

    fee_mult = bps_to_mult(cfg.fee_bps)
    slip_mult = bps_to_mult(cfg.slippage_bps)

    price_client = JupiterPriceClient()
    events = load_events(SIGNALS_PATH)

    cash = cfg.starting_cash

    # positions per mint
    # positions[mint] = {"units": float, "avg_entry": float, "entry_ts": float}
    positions: dict[str, dict] = {}

    trades = []
    equity = []

    skipped = {
        "skip_missing_fields": 0,
        "skip_err": 0,
        "skip_allowlist": 0,
        "skip_signal_type": 0,
        "skip_min_amount": 0,
        "skip_min_dominance": 0,
        "skip_no_price": 0,
        "skip_insufficient_cash": 0,
        "skip_no_position": 0,
    }

    def mark_equity(ts: float) -> None:
        nonlocal cash
        total_pos_value = 0.0
        any_price = False

        for m, p in positions.items():
            if float(p.get("units", 0.0)) <= 0:
                continue
            px = price_client.get_price(m)
            if px is None:
                continue
            any_price = True
            total_pos_value += float(p["units"]) * float(px)

        if not any_price:
            total_pos_value = 0.0

        equity.append(
            {
                "ts": ts,
                "cash_usd": cash,
                "position_value_usd": total_pos_value,
                "equity_usd": cash + total_pos_value,
                "open_positions": sum(1 for p in positions.values() if float(p.get("units", 0.0)) > 0),
            }
        )

    def maybe_exit(ts: float, mint: str, price: float, trigger_sig: str) -> None:
        nonlocal cash

        pos = positions.get(mint)
        if not pos or float(pos.get("units", 0.0)) <= 0:
            skipped["skip_no_position"] += 1
            return

        units = float(pos["units"])
        avg_entry = float(pos["avg_entry"])
        entry_ts = float(pos["entry_ts"])

        if avg_entry <= 0:
            return

        pnl_pct = ((price / avg_entry) - 1.0) * 100.0
        held_s = ts - entry_ts

        exit_reason = None
        if pnl_pct >= cfg.take_profit_pct:
            exit_reason = "take_profit"
        elif pnl_pct <= -abs(cfg.stop_loss_pct):
            exit_reason = "stop_loss"
        elif held_s >= cfg.hold_seconds:
            exit_reason = "time_exit"

        if not exit_reason:
            return

        sell_units = units * float(cfg.sell_fraction)
        if sell_units <= 0:
            return

        gross_usd = sell_units * price
        fees_usd = gross_usd * fee_mult
        slip_usd = gross_usd * slip_mult
        net_proceeds = gross_usd - fees_usd - slip_usd

        cash += net_proceeds
        pos["units"] = units - sell_units

        if pos["units"] <= 1e-12:
            pos["units"] = 0.0
            pos["avg_entry"] = 0.0
            pos["entry_ts"] = 0.0

        trades.append(
            {
                "ts": ts,
                "signature": trigger_sig,
                "side": "SELL",
                "mint": mint,
                "reason": exit_reason,
                "price_usd": price,
                "units": sell_units,
                "gross_usd": gross_usd,
                "fees_usd": fees_usd,
                "slippage_usd": slip_usd,
                "net_usd": net_proceeds,
                "cash_usd": cash,
                "pnl_pct_vs_entry": pnl_pct,
            }
        )

    for e in events:
        sig = e.get("signature")
        signal = e.get("signal")
        top_mint = e.get("top_mint")
        top_amount = float(e.get("top_amount", 0.0) or 0.0)
        dominance = float(e.get("dominance", 0.0) or 0.0)
        ts = float(e.get("_ts", time.time()) or time.time())

        if e.get("err") is not None:
            skipped["skip_err"] += 1
            continue
        if not sig or not top_mint:
            skipped["skip_missing_fields"] += 1
            continue

        if allow is not None and top_mint not in allow:
            skipped["skip_allowlist"] += 1
            continue

        if signal not in allowed_signals:
            skipped["skip_signal_type"] += 1
            continue

        if top_amount < cfg.min_signal_amount:
            skipped["skip_min_amount"] += 1
            continue

        if dominance < cfg.min_dominance:
            skipped["skip_min_dominance"] += 1
            continue

        price = price_client.get_price(top_mint)
        if price is None:
            skipped["skip_no_price"] += 1
            continue
        price = float(price)

        # exit check for same mint
        maybe_exit(ts=ts, mint=top_mint, price=price, trigger_sig=sig)

        # entry sizing
        trade_units = top_amount * cfg.copy_fraction

        gross_usd = trade_units * price
        fees_usd = gross_usd * fee_mult
        slip_usd = gross_usd * slip_mult
        total_cost = gross_usd + fees_usd + slip_usd

        if total_cost > cash:
            skipped["skip_insufficient_cash"] += 1
            continue

        cash -= total_cost

        pos = positions.get(top_mint, {"units": 0.0, "avg_entry": 0.0, "entry_ts": 0.0})
        prev_units = float(pos["units"])
        new_units = prev_units + trade_units

        if prev_units <= 0:
            pos["avg_entry"] = price
            pos["entry_ts"] = ts
        else:
            pos["avg_entry"] = ((prev_units * float(pos["avg_entry"])) + (trade_units * price)) / new_units

        pos["units"] = new_units
        positions[top_mint] = pos

        trades.append(
            {
                "ts": ts,
                "signature": sig,
                "side": "BUY",
                "mint": top_mint,
                "signal": signal,
                "observed_amount": top_amount,
                "copy_fraction": cfg.copy_fraction,
                "units": trade_units,
                "price_usd": price,
                "gross_usd": gross_usd,
                "fees_usd": fees_usd,
                "slippage_usd": slip_usd,
                "total_cost_usd": total_cost,
                "cash_usd": cash,
                "position_units_after": positions[top_mint]["units"],
                "avg_entry_after": positions[top_mint]["avg_entry"],
            }
        )

        mark_equity(ts)

    if trades:
        df_trades = pd.DataFrame(trades)
        df_trades.to_csv(OUT_TRADES, index=False)
        console.print(f"[green]Saved[/green] {OUT_TRADES}")
    else:
        console.print("[yellow]No trades executed. Thresholds too strict or no qualifying signals.[/yellow]")

    if equity:
        df_eq = pd.DataFrame(equity)
        df_eq.to_csv(OUT_EQUITY, index=False)
        console.print(f"[green]Saved[/green] {OUT_EQUITY}")

        start = cfg.starting_cash
        end = float(df_eq["equity_usd"].iloc[-1])
        ret = (end / start - 1.0) * 100.0
        console.print({"starting_cash": start, "ending_equity": end, "return_pct": ret})

    console.print({"skipped": skipped})


if __name__ == "__main__":
    main()
