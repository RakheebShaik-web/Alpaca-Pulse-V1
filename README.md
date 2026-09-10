# Pulse V1 — Institutional Footprint Trading System

Automated US stock trading system using Alpaca Markets. Pre-market gap scanner + Opening Range Breakout strategy with institutional-grade risk management.

## Strategy

| Component | Details |
|-----------|---------|
| **Setup** | Pre-market gap scan (0.3%+ gap, 100k+ volume) |
| **Entry** | Opening Range Breakout (9:30-9:45 AM range) |
| **Confirmation** | VWAP + Volume + Multi-factor scoring |
| **Stop Loss** | ATR-based (1.5x ATR distance) |
| **Take Profit** | 2:1 reward-to-risk |
| **Time Exit** | 3:50 PM (10 mins before close) |
| **Daily Limits** | Max 3 trades, $200 loss, $150 profit target |

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Dashboard     │────▶│   FastAPI       │────▶│   Alpaca        │
│   (Vercel)      │◀────│   (Render)      │◀────│   Markets       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │
        │                       ▼
        │               ┌─────────────────┐
        └──────────────▶│   Discord       │
                        │   Alerts        │
                        └─────────────────┘
```

## Repositories

| Repo | Purpose | Deploy |
|------|---------|--------|
| [Alpaca-Pulse-V1](https://github.com/RakheebShaik-web/Alpaca-Pulse-V1) | Backend + Strategy | Render |
| [Pulse-V1-dashboard](https://github.com/RakheebShaik-web/Pulse-V1-dashboard) | Frontend Dashboard | Vercel |

## 6-Month Backtest Results ($20k capital, $50/trade)

| Rank | Symbol | Return | Win Rate | Trades | Profit Factor | Max DD |
|------|--------|--------|----------|--------|---------------|--------|
| 🥇 | AMZN | +2.19% | 50% | 14 | 7.79 | 0.34% |
| 🥈 | SPY | +1.12% | 58% | 12 | 6.76 | 0.38% |
| 🥉 | AAPL | +1.09% | 62% | 21 | 2.85 | 0.39% |
| 4 | GOOGL | +0.97% | 60% | 15 | 2.33 | 0.49% |
| 5 | AMD | +0.48% | 45% | 20 | 1.46 | 0.57% |
| 6 | QQQ | +0.36% | 50% | 20 | 1.30 | 0.75% |
| 7 | META | +0.17% | 61% | 18 | 1.29 | 0.41% |
| 8 | TSLA | +0.37% | 55% | 22 | 1.26 | 0.93% |
| 9 | MSFT | +0.06% | 50% | 20 | 1.07 | 0.59% |

**Universe:** AMZN, SPY, AAPL, GOOGL, AMD, QQQ, META, TSLA, MSFT

## Backend API

### Start

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | System status |
| `/api/account` | GET | Account details |
| `/api/positions` | GET | Active positions |
| `/api/trades` | GET | Trade history |
| `/api/scan` | GET | Pre-market scan results |
| `/api/clock` | GET | Market clock |
| `/api/daily` | GET | Daily statistics |
| `/api/start` | POST | Start trading (admin) |
| `/api/stop` | POST | Stop trading (admin) |
| `/api/close-all` | POST | Close all positions (admin) |
| `/api/cancel-all` | POST | Cancel all orders (admin) |

### Environment Variables

```
ALPACA_API_KEY=***
ALPACA_SECRET_KEY=***
PAPER_TRADING=true
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... (optional)
ADMIN_API_KEY=your_admin_password
```

## Render Deployment

1. Create new Web Service
2. Import `RakheebShaik-web/Alpaca-Pulse-V1`
3. Set environment variables
4. Deploy

## Vercel Dashboard

See [Pulse-V1-dashboard](https://github.com/RakheebShaik-web/Pulse-V1-dashboard) for the frontend.

## Risk Warnings

- **Past performance ≠ future results**
- Start with paper trading
- $50/trade = max $150/day loss
- Never risk more than you can afford to lose

## License

MIT
