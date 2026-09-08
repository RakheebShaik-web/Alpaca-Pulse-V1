# Algo Trading System

Pre-Market Momentum + Opening Range Breakout strategy for US stocks.

## Strategy Overview

| Component | Details |
|-----------|---------|
| **Setup** | Pre-market gap scan (2%+ gap, 100k+ volume) |
| **Entry** | Opening Range Breakout (9:30-9:45 AM range) |
| **Confirmation** | VWAP + EMA9 trend filter |
| **Stop Loss** | Fixed $50 per trade |
| **Take Profit** | 1.5:1 reward-to-risk |
| **Time Exit** | 10:50 AM (avoid midday chop) |
| **Daily Limits** | Max 3 trades, $100 loss, $150 profit target |

## Backtest Results (60 days, Yahoo Finance data)

| Symbol | Return | Win Rate | Trades | Profit Factor | Max DD |
|--------|--------|----------|--------|---------------|--------|
| **TSLA** | **+1.28%** | **60.0%** | 35 | **1.75** | 0.92% |
| SPY | +0.66% | 52.6% | 19 | 1.87 | 0.93% |
| AMD | +0.03% | 39.4% | 33 | 0.89 | 1.14% |
| NVDA | -0.73% | 45.5% | 33 | 0.67 | 1.35% |
| COIN | -0.65% | 46.3% | 41 | 0.71 | 1.34% |

**Best performer: TSLA** — 60% win rate, 1.75 profit factor, only 0.92% max drawdown.

### Monthly Projection (TSLA-like performance)

| Metric | Value |
|--------|-------|
| Avg daily PnL | ~$43 |
| Monthly (20 days) | ~$860 |
| Win rate needed for $150/day | ~70% |

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your Alpaca API keys
```

### 3. Get Alpaca API keys

1. Sign up at [alpaca.markets](https://alpaca.markets)
2. Get paper trading keys first
3. Add them to `.env`

### 4. Set up Discord webhook (optional)

1. In Discord, go to Server Settings → Integrations → Webhooks
2. Create a webhook and copy the URL
3. Add to `.env` as `DISCORD_WEBHOOK_URL`

## Usage

### Backtest

```bash
# Backtest a symbol
python backtest.py SPY 60

# Backtest with Discord alerts
python backtest.py TSLA 60 "https://discord.com/api/webhooks/..."
```

### Paper Trade

```bash
# Make sure PAPER_TRADING=true in .env
python live_trader.py
```

### Live Trade

```bash
# Set PAPER_TRADING=false in .env
python live_trader.py
```

## Discord Alerts

The bot sends formatted alerts for:

- 🔍 Pre-market scan results
- 🟢/🔴 Trade entries with entry/stop/target
- ✅/❌ Trade exits with PnL
- 📈 Daily summary

## Risk Warnings

1. **PDT Rule**: With $20k in a margin account, you're limited to 3 day trades per 5-day period. Use a **cash account** to avoid this.
2. **Past performance ≠ future results** — backtests don't account for slippage, fills, or changing market conditions.
3. **Start with paper trading** — prove the strategy works with your execution before risking real money.
4. **Never risk more than you can afford to lose** — $50/trade means max $150/day loss.

## File Structure

```
algo-trading/
├── .env                  # API keys (don't commit)
├── .env.example          # Template
├── config.py             # Strategy parameters
├── backtest.py           # Backtesting engine
├── live_trader.py        # Live trading bot
├── discord_notifier.py   # Discord alerts
├── requirements.txt      # Dependencies
└── trading.log           # Trade log (generated)
```

## Tuning Parameters

Edit `config.py` to adjust:

- `gap_threshold` — minimum gap % (default 0.3%)
- `risk_per_trade` — $ risk per trade (default $50)
- `rr_ratio` — reward-to-risk ratio (default 1.5)
- `max_trades_per_day` — daily trade limit (default 3)
- `universe` — stock symbols to scan
