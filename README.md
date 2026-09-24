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

## The rules

**Entry:**
- VWAP deviation > 1.5 std dev
- Volume confirmation
- Narrow opening range (< 0.3%)
- Latest completed bar moves back toward VWAP
- ADX at or below 25 (range/transition regime)
- Score 4+/8 points

**Position sizing:**
- No more than $50 planned risk per trade; realized losses can exceed this through gaps or slippage
- Max 2 new trades per day
- Max 10% of capital per name

**Exit:**
- Hit target (2:1 RR)
- Hit stop (ATR-based)
- Trailing stop locks in profits after 1R
- 3:50 PM hard close

**When it stays in cash:**
- Strong trend (ADX > 25)
- Max daily loss hit ($100)
- 2 consecutive losses
- For 45 minutes after a losing exit
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
