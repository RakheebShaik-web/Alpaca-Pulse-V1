# Pulse V1

> I built this because I was tired of strategies that looked good on paper but lost money in live markets.

A 24/7 automated trading system for US stocks. Runs while you sleep, while you work, while you pretend to understand crypto.

---

## How it actually works

Most trading bots are just moving averages and prayers. This one's different:

**What it looks for:**
- Price freaking out relative to VWAP (institutions start caring around 1.5 std dev)
- Volume confirming someone actually gives a shit
- Narrow opening ranges (volatility compression = explosive moves)
- Specific hours when real money moves the market

**What it ignores:**
- Noise. Most "setups" are just the market being random.
- Your FOMO. If the math doesn't work, it doesn't trade.
- Defense contractors, banks, and whatever PLTR is.

**The boring truth:**
Some days it won't trade at all. That's the point. Professional traders wait days for the right setup. Your bot does the same.

---

## Backtested performance (6 months, $20k paper)

| Symbol | Return | Win Rate | Trades | Max DD |
|--------|--------|----------|--------|--------|
| AMZN | +2.19% | 50% | 14 | 0.34% |
| SPY | +1.12% | 58% | 12 | 0.38% |
| AAPL | +1.09% | 62% | 21 | 0.39% |
| GOOGL | +0.97% | 60% | 15 | 0.49% |
| AMD | +0.48% | 45% | 20 | 0.57% |

Yeah, the returns look small. That's the point. I'd rather make $50/day consistently than $500 one day and lose $400 the next.

---

## The rules

**Entry:**
- VWAP deviation > 1.5 std dev
- Volume > 1.5x average
- Narrow opening range (< 0.3%)
- Price reverts through VWAP (confirmation)
- Score 4+/8 points

**Position sizing:**
- Exactly $50 per trade
- Max 3 positions
- Max 10% of capital per name

**Exit:**
- Hit target (2:1 RR)
- Hit stop (ATR-based)
- Trailing stop locks in profits after 1R
- 3:50 PM hard close

**When it stays in cash:**
- Choppy market (ADX < 15)
- Max daily loss hit ($200)
- 3 consecutive losses
- Account drawdown > 5%
- It's 2 PM on Friday and nothing makes sense

---

## Running it

```bash
git clone https://github.com/RakheebShaik-web/Alpaca-Pulse-V1.git
cd Alpaca-Pulse-V1
pip install -r requirements.txt
uvicorn main:app --port 8000
```

Dashboard: `https://alpaca-bot-v2.vercel.app`

Press Start. That's it.

---

## Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI + Python |
| Frontend | Vanilla HTML/JS (no frameworks, no bloat) |
| Broker | Alpaca Markets |
| Data | yfinance |
| Hosting | Render (API) + Vercel (dashboard) |
| Alerts | Discord |
| Keep-alive | GitHub Actions |

---

## Disclaimer

I'm not a financial advisor. I'm just a guy who got tired of losing money. This works for me. It might not work for you. Don't risk money you can't afford to lose.

Also, past performance doesn't guarantee future results. If it did, I'd be on a beach somewhere instead of writing README files.

---

## Issues?

Open one. I actually read them.
