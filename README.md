# Onchain Trader Intelligence (Solana)

A lightweight, end-to-end demo that watches Solana wallets in real time, extracts SPL token transfer signals, and runs a paper execution simulation using Jupiter spot prices.

This repository is intentionally **demo-complete and bounded**:
**watch → signal → paper trade → CSV outputs**.  

No production trading.

---

## What this project does

### 1) Realtime wallet watcher
- Subscribes to Solana websocket logs for one or more wallets (A, B, C)
- Fetches full transactions via RPC (Helius)
- Extracts SPL token transfers involving the watched wallet
- Computes a simple signal:
  - `top_mint`
  - `top_amount`
  - `total_amount`
  - `dominance` (top / total)
- Classifies activity:
  - `normal_transfer`
  - `large_transfer`
  - `whale_activity`
- Writes newline-delimited JSON to:
  - `artifacts/realtime_signals.jsonl`

### 2) Paper execution engine
- Reads `artifacts/realtime_signals.jsonl`
- Applies tier-based filters and thresholds
- Fetches spot prices from Jupiter
- Simulates:
  - position sizing
  - fees + slippage
  - take profit / stop loss / time exits
- Outputs:
  - `artifacts/paper_trades.csv`
  - `artifacts/paper_equity_curve.csv`

This shows **end-to-end system thinking**: realtime ingestion → inference → execution → reporting.

---

## Repository structure

```
src/
  realtime/
    watch_wallet.py         # websocket subscriber + signal writer
    execute_signals.py      # paper execution simulator
  ingest/
    solana_rpc.py           # fetch tx by signature
    extract_transfers.py    # parse SPL transfers
  pricing/
    jupiter_prices.py       # Jupiter spot price lookup

artifacts/
  realtime_signals.jsonl    # generated
  paper_trades.csv          # generated
  paper_equity_curve.csv    # generated

.env                        # local config (not committed)
```

---

## Requirements

- Python 3.10+
- Solana RPC endpoint (Helius recommended)
- Solana WebSocket endpoint

Core libraries:
- python-dotenv
- websockets
- httpx
- pandas
- rich

---

## Setup

### 1) Create and activate a virtual environment (Windows)

```
python -m venv .venv
.venv\Scripts\activate
```

### 2) Install dependencies

```
pip install -r requirements.txt
```

---

## Environment configuration

Create a `.env` file in the project root:

```
SOLANA_RPC=https://mainnet.helius-rpc.com/?api-key=YOUR_KEY
SOLANA_WS=wss://api.mainnet-beta.solana.com

WALLET_A=DEXVS3su4dZQWTvvPnLDJLRK1CeeKG6K3QqdzthgAkNV
WALLET_B=7rtiKSUDLBm59b1SBmD9oajcP8xE64vAGSMbAN5CXy1q
WALLET_C=5WDfGzcVDtkTz5TpbnzoeJgYd8pHPUxTem2Tc3xVf2Cu

# =========================
# Paper execution settings
# =========================

PAPER_TIER=LOW_RISK
PAPER_STARTING_CASH=1000
PAPER_COPY_FRACTION=0.05

PAPER_FEE_BPS=20
PAPER_SLIPPAGE_BPS=30

PAPER_MIN_SIGNAL_AMOUNT=0.01
PAPER_MIN_DOMINANCE=0.3

# Allow looser thresholds while testing
PAPER_TEMP_LOWER_THRESHOLDS=1

PAPER_HOLD_SECONDS=600
PAPER_TAKE_PROFIT_PCT=1.0
PAPER_STOP_LOSS_PCT=0.5
PAPER_SELL_FRACTION=1.0
```

---

## Quickstart (recommended path)

### Step 1: Watch a single wallet
To avoid excessive logs, watch only one wallet (example: C).

```
set WATCH_LABEL=C
python -m src.realtime.watch_wallet
```

Let it run for 1–2 minutes, then stop with `Ctrl + C`.

Captured events are written to:
```
artifacts/realtime_signals.jsonl
```

### Step 2: Run paper execution

```
python -m src.realtime.execute_signals
```

### Step 3: Review outputs

```
artifacts/paper_trades.csv
artifacts/paper_equity_curve.csv
```

---

## Signal logic (intentionally simple)

For each transaction touching a watched wallet:

1. Extract SPL token transfers
2. Rank by absolute amount
3. Compute dominance = top / total
4. Assign label:
   - `whale_activity` ≥ 10 units
   - `large_transfer` ≥ 1 unit
   - otherwise `normal_transfer`

---

## Paper execution logic (high level)

- Load all recorded signals
- Filter by:
  - signal type
  - minimum amount
  - dominance
  - available price
- Fetch Jupiter spot price
- Simulate buy
- Exit on:
  - take profit
  - stop loss
  - max hold time

Everything is deterministic and CSV-backed for inspection.

---

## Notes

- Many logs are expected when watching active wallets
- `skip_no_price` means Jupiter has no spot price for that mint
- `PAPER_TEMP_LOWER_THRESHOLDS=1` is for demo velocity only
