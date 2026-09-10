# Pulse V1

> I built this because I was tired of strategies that looked good on paper but bled money in live markets. This is what actually works for me.

A 24/7 automated trading bot for US stocks. Runs while I sleep, drinks coffee, and pretends to understand crypto.

---

## What it does

Scans the market every morning, finds setups that actually have an edge, and trades them. No FOMO. No revenge trading. No "this time it'll be different."

**The short version:**
- Watches for price to freak out relative to VWAP
- Checks if institutions are actually participating (volume)
- Only pulls the trigger when the math says it's worth it
- Walks away when things get choppy

---

## Why I built this

I tried the ALMA crossover thing. Worked great in backtests. Lost money live. Same story with ORB breakouts and mean reversion. Every strategy worked until it didn't.

So I stopped looking for the holy grail and started focusing on **risk management**. This bot is boring by design. It's supposed to be boring. Boring pays rent.

---

## The actual rules

**When it trades:**
- Price deviates >1.5 std dev from VWAP (institutions start caring)
- Volume confirms someone actually cares
- It's during the hours when real money moves (9:45-11 AM, 2-3:30 PM)
- The setup scores at least 4/8 on my stupid little scoring system

**When it doesn't trade:**
- Choppy market (ADX too low)
- I've already lost enough today ($200 max)
- I'm on a losing streak (3 in a row and I'm done)
- It's 2 PM on a Friday and nothing makes sense

**Position sizing:**
- Exactly $50 per trade. Not $49, not $51. Fifty bucks.
- Max 3 positions at once because I don't trust myself with more
- Move stop to breakeven after 1R profit because I like not losing money
- Trail the winner because I'm greedy but not stupid

---

## Backtest results (6 months, $20k paper)

| Symbol | Return | Win Rate | Trades | Max DD |
|--------|--------|----------|--------|--------|
| AMZN | +2.19% | 50% | 14 | 0.34% |
| SPY | +1.12% | 58% | 12 | 0.38% |
| AAPL | +1.09% | 62% | 21 | 0.39% |
| GOOGL | +0.97% | 60% | 15 | 0.49% |
| AMD | +0.48% | 45% | 20 | 0.57% |

Yeah, the returns look small. That's the point. I'd rather make $50/day consistently than $500 one day and lose $400 the next.

---

## Running it

```bash
git clone https://github.com/RakheebShaik-web/Alpaca-Pulse-V1.git
cd Alpaca-Pulse-V1
pip install -r requirements.txt
uvicorn main:app --port 8000
```

Then open `https://alpaca-bot-v2.vercel.app` and press Start.

---

## What you need

- Alpaca account (free paper trading works fine)
- A Render account (free tier is fine for testing)
- A Discord webhook if you want trade alerts (optional)
- The patience to let a boring strategy do its thing

---

## Disclaimer

I'm not a financial advisor. I'm just a guy who got tired of losing money on bad trades. This works for me. It might not work for you. Don't risk money you can't afford to lose.

Also, past performance doesn't guarantee future results. If it did, I'd be on a beach somewhere instead of writing README files.

---

## Issues?

Open an issue. I actually read them.
