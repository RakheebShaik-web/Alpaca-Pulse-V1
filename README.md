# Pulse V1

Python/FastAPI backend for the Institutional Footprint stock strategy. Alpaca executes orders; Yahoo Finance supplies minute bars. Paper trading is the default.

## Risk and exits

- **$50 planned risk budget per trade**, calculated as shares times the distance from the signal price to the stop.
- Whole shares are rounded down. The existing 10% position-value cap and available buying power may reduce risk below $50. Skip when even one share exceeds a limit.
- **1:2 risk/reward** (`rr_ratio = 2.0` means reward divided by risk). A fully sized $50-risk trade targets $100 before costs.
- Stop distance: 1.5 x ATR(14), retaining the intraday strategy's existing setting. Target distance: twice the rounded stop distance.
- Breakeven activates at +1R; a 2 x ATR trail tightens thereafter. Stops never widen. Trailing exits can realize less than the initial 2R target.
- Three daily entry submissions and three simultaneous tracked positions, with daily loss and consecutive-loss limits. Counters roll over by US Eastern date.
- Entry restrictions never disable management of existing positions. `/api/stop` pauses new entries while the monitor continues handling existing exposure.

$50 is a **planned stop-risk budget**, not a guaranteed realized-loss ceiling. Entries use market orders, and gaps, slippage and fees can exceed it or alter the realized reward/risk. The 2R target is a baseline from fixed-risk exit planning, not a claim of optimal or profitable performance.

## Local setup

Requires Python 3.11+.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:ALPACA_API_KEY = 'your-paper-key'
$env:ALPACA_SECRET_KEY = 'your-paper-secret'
$env:ADMIN_API_KEY = 'a-long-random-secret'
$env:PAPER_TRADING = 'true'
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Set `DISCORD_WEBHOOK_URL` only if alerts are wanted. Environment variables must be supplied by your shell or hosting platform; a `.env` file is not loaded automatically.

Admin requests require `Authorization: Bearer <ADMIN_API_KEY>`. A missing server key rejects admin requests, and comparison is case-sensitive. Start via `POST /api/start`; inspect `/api/status` for reconciliation errors. The backend starts with new entries disabled. No frontend is included in this repository.

`POST /api/close-all` requests closure and returns HTTP 202; it does not claim immediate fills. Conflicting orders are canceled first, then remaining exposure is closed. State and P&L update from confirmed broker fills. Partial fills remain tracked. Uncertain submissions retain their client order IDs and are not blindly retried.

## Persistence and deployment

Use one application process/worker per account and a persistent disk. Set `BOT_STATE_PATH` for the state file and `TRADES_CSV_PATH` for CSV logging; the journal uses `data/trade_journal.json`. Mount the `data` directory so all three survive restarts. Render/Railway configurations require a continuously running service; Vercel's serverless configuration is not suitable for the persistent trading monitor.

Restart recovery preserves saved stops and trailing state, restores the strategy's position map, and reads actual positions/orders from Alpaca. Previously untracked broker positions get direction-correct fallback levels (0.5% stop, 2R target). Review these recovered positions. Legacy flat positions without an identifiable exit fill block new entries for reconciliation instead of fabricating P&L or discarding history. Unknown submission outcomes are exposed in `/api/status`; use the persisted client order ID to resolve them with the broker before altering state. Corrupt state and backup files fail closed.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use mocked brokers and synthetic data; they do not place orders or send notifications. GitHub Actions runs the same suite.

## Backtesting

The replay uses the same `InstitutionalStrategy`, `Position` exits, sizing policy and entry gates as the live bot. It exposes only completed bars and enters at the following bar's open. Stops include adverse gaps and configurable slippage; when both stop and target touch within one bar, the replay assumes the stop fires first. Open positions at the end remain marked to market and are reported separately.

```powershell
.\.venv\Scripts\python.exe backtest.py SPY --days 7
.\.venv\Scripts\python.exe backtest.py SPY --csv historical-SPY.csv
.\.venv\Scripts\python.exe run_all_backtests.py
```

CSV columns: timestamp, Open, High, Low, Close, Volume. Naive timestamps mean US Eastern; timezone-aware timestamps are converted. Supply minute bars. Yahoo requests are limited to seven days; longer periods require your own CSV. The universe runner produces independent single-symbol studies, not a portfolio simulation.

The replay does not model broker latency, order rejections, partial fills, short borrow costs/availability, or historical earnings exclusions. Validate those separately in paper trading. The old ORB results are removed because they did not validate the live strategy. No new performance claim is made.
