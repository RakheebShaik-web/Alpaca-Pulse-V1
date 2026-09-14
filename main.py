#!/usr/bin/env python3
"""
FastAPI server for the trading system.
"""
import os
import asyncio
import logging
from datetime import datetime

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import config
from alpaca_trader import AlpacaTrader
from institutional_strategy import get_et_now

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Pulse V1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

trader = AlpacaTrader()
bot_status = "stopped"


@app.get("/")
async def root():
    return {"status": "ok", "service": "Pulse V1"}


@app.get("/api/status")
async def get_status():
    global bot_status
    account = trader.get_account()
    equity = float(account.get('equity', 0)) if account else 0
    last_equity = float(account.get('last_equity', equity)) if account else equity
    buying_power = float(account.get('buying_power', 0)) if account else 0
    positions = trader.get_positions()

    return {
        "status": bot_status,
        "mode": "paper",
        "daily_pnl": round(equity - last_equity, 2),
        "total_trades": 0,
        "active_positions": len(positions),
        "portfolio_value": round(equity, 2),
        "buying_power": round(buying_power, 2),
    }


@app.get("/api/positions")
async def get_positions():
    positions = trader.get_positions()
    result = []
    for p in positions:
        entry = p.get('entry_price', 0)
        current = p.get('current_price', 0)
        qty = p.get('qty', 0)
        side = p.get('side', 'long')
        risk = config.risk_per_trade / qty if qty > 0 else 0

        if side == 'long':
            sl = round(entry - risk, 2)
            tp1 = round(entry + risk * 0.8, 2)
            tp2 = round(entry + risk * 1.5, 2)
        else:
            sl = round(entry + risk, 2)
            tp1 = round(entry - risk * 0.8, 2)
            tp2 = round(entry - risk * 1.5, 2)

        result.append({
            "symbol": p.get('symbol'),
            "side": side,
            "remaining": qty,
            "entry": round(entry, 2),
            "sl": sl, "tp1": tp1, "tp2": tp2,
            "current_price": round(current, 2),
            "pnl": round(p.get('unrealized_pl', 0), 2),
        })
    return result


@app.get("/api/trades")
async def get_trades():
    return {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl": 0}


@app.get("/api/clock")
async def get_clock():
    now = get_et_now()
    return {
        "time": now.strftime("%I:%M:%S %p ET"),
        "date": now.strftime("%m/%d/%Y"),
        "market_open": True,
    }


@app.post("/api/start")
async def start_bot():
    global bot_status
    bot_status = "running"
    return {"status": "started"}


@app.post("/api/stop")
async def stop_bot():
    global bot_status
    bot_status = "stopped"
    return {"status": "stopped"}


@app.post("/api/close-all")
async def close_all():
    trader.close_all_positions()
    return {"status": "ok"}


@app.post("/api/cancel-all")
async def cancel_all():
    trader.cancel_all_orders()
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
