#!/usr/bin/env python3
"""
FastAPI server for the trading system.
Institutional Footprint Strategy — multi-factor alpha generation.
"""
import os
import asyncio
import logging
from datetime import datetime, time as dtime, timedelta
from typing import Optional, List, Dict, Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pytz

from config import config
from discord_notifier import DiscordNotifier
from state_store import load_state, save_state
from data_feed import DataFeed
from institutional_strategy import InstitutionalStrategy, SignalDirection, get_et_now, get_et_time
from csv_log import get_trade_summary
from trade_journal import journal
from alpaca_trader import AlpacaTrader

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

system = None


ADMIN_KEY = os.environ.get("ADMIN_API_KEY", "")


def check_admin(x_admin_api_key: str = Header(default="")):
    """Check admin API key."""
    if not ADMIN_KEY:
        return True
    if x_admin_api_key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Invalid key")
    return True


@app.get("/")
async def root():
    return {"status": "ok", "service": "Pulse V1"}


@app.get("/api/status")
async def get_status(_: bool = Header(default=True)):
    check_admin(_.header.default if hasattr(_, 'header') else "")
    uptime = 0.0
    if system and system.start_time:
        uptime = (datetime.utcnow() - system.start_time).total_seconds()
    
    account = None
    equity = 0
    last_equity = 0
    buying_power = 0
    
    if system and system.trader:
        account = system.trader.get_account()
        if account:
            equity = float(account.get('equity', 0))
            last_equity = float(account.get('last_equity', equity))
            buying_power = float(account.get('buying_power', 0))
    
    return {
        "status": system.status if system else "stopped",
        "mode": "paper" if os.environ.get("PAPER_TRADING", "true") == "true" else "live",
        "uptime": uptime,
        "daily_pnl": round(equity - last_equity, 2),
        "total_trades": system.state.trades_today if system else 0,
        "active_positions": len(system.state.all_positions()) if system else 0,
        "portfolio_value": round(equity, 2),
        "buying_power": round(buying_power, 2),
        "last_scan_at": None,
        "last_scan_error": None,
    }


@app.get("/api/positions")
async def get_positions(x_admin_api_key: str = Header(default="")):
    check_admin(x_admin_api_key)
    if not system or not system.trader:
        return []
    
    positions = system.trader.get_positions()
    result = []
    for p in positions:
        entry = p.get('entry_price', 0)
        current = p.get('current_price', 0)
        qty = p.get('qty', 0)
        side = p.get('side', 'long')
        
        risk_per_share = config.risk_per_trade / qty if qty > 0 else 0
        if side == 'long':
            sl = round(entry - risk_per_share, 2)
            tp1 = round(entry + risk_per_share * 0.8, 2)
            tp2 = round(entry + risk_per_share * 1.5, 2)
        else:
            sl = round(entry + risk_per_share, 2)
            tp1 = round(entry - risk_per_share * 0.8, 2)
            tp2 = round(entry - risk_per_share * 1.5, 2)
        
        result.append({
            "symbol": p.get('symbol'),
            "side": side,
            "remaining": qty,
            "entry": round(entry, 2),
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "current_price": round(current, 2),
            "market_value": round(current * qty, 2),
            "cost_basis": round(entry * qty, 2),
            "pnl": round(p.get('unrealized_pl', 0), 2),
            "pnl_pct": round(p.get('unrealized_plpc', 0) * 100, 2) if p.get('unrealized_plpc') else 0,
            "opened_at": p.get('opened_at'),
            "last_event": "ENTRY_" + side.upper(),
        })
    return result


@app.get("/api/trades")
async def get_trades(x_admin_api_key: str = Header(default="")):
    check_admin(x_admin_api_key)
    return get_trade_summary()


@app.get("/api/closed-positions")
async def get_closed_positions(x_admin_api_key: str = Header(default="")):
    check_admin(x_admin_api_key)
    summary = get_trade_summary()
    return {
        "total_closed": summary.get("total_trades", 0),
        "wins": summary.get("wins", 0),
        "losses": summary.get("losses", 0),
        "win_rate": summary.get("win_rate", 0),
        "total_pnl": summary.get("total_pnl", 0),
        "avg_pnl": summary.get("total_pnl", 0) / max(1, summary.get("total_trades", 0)),
        "avg_win": summary.get("avg_win", 0),
        "avg_loss": summary.get("avg_loss", 0),
    }


@app.get("/api/pnl-curve")
async def get_pnl_curve(x_admin_api_key: str = Header(default="")):
    check_admin(x_admin_api_key)
    if not system:
        return []
    return system.pnl_curve


@app.get("/api/symbol-stats")
async def get_symbol_stats(x_admin_api_key: str = Header(default="")):
    check_admin(x_admin_api_key)
    return []


@app.get("/api/trade-logs")
async def get_trade_logs(x_admin_api_key: str = Header(default="")):
    check_admin(x_admin_api_key)
    if not system or not system.trader:
        return []
    
    orders = system.trader.get_orders(status="closed")
    logs = []
    for o in orders[:50]:
        filled_at = o.get('filled_at')
        submitted_at = o.get('submitted_at')
        time_str = ''
        if filled_at:
            time_str = filled_at.isoformat() if hasattr(filled_at, 'isoformat') else str(filled_at)
        elif submitted_at:
            time_str = submitted_at.isoformat() if hasattr(submitted_at, 'isoformat') else str(submitted_at)
        
        logs.append({
            "time": time_str,
            "symbol": o.get('symbol', ''),
            "event": o.get('type', '').upper(),
            "side": o.get('side', ''),
            "price": o.get('filled_avg_price', 0),
            "shares": o.get('filled_qty', 0),
            "pnl": o.get('pnl', 0),
        })
    return logs


@app.get("/api/clock")
async def get_clock(x_admin_api_key: str = Header(default="")):
    check_admin(x_admin_api_key)
    now = get_et_now()
    return {
        "time": now.strftime("%I:%M:%S %p ET"),
        "date": now.strftime("%m/%d/%Y"),
        "market_open": (config.morning_window_start <= now.time() <= config.trading_end),
    }


@app.post("/api/start")
async def start_bot(x_admin_api_key: str = Header(default="")):
    global system
    check_admin(x_admin_api_key)
    if system and system.status == "running":
        return {"status": "already running"}
    if system:
        system.start()
    return {"status": "started"}


@app.post("/api/stop")
async def stop_bot(x_admin_api_key: str = Header(default="")):
    global system
    check_admin(x_admin_api_key)
    if system:
        system.stop()
    return {"status": "stopped"}


@app.post("/api/close-all")
async def close_all(x_admin_api_key: str = Header(default="")):
    check_admin(x_admin_api_key)
    if system and system.trader:
        system.trader.close_all_positions()
    return {"status": "closing all"}


@app.post("/api/cancel-all")
async def cancel_all(x_admin_api_key: str = Header(default="")):
    check_admin(x_admin_api_key)
    if system and system.trader:
        system.trader.cancel_all_orders()
    return {"status": "cancelling all"}


@app.get("/api/journal")
async def get_journal(x_admin_api_key: str = Header(default="")):
    check_admin(x_admin_api_key)
    return journal.get_summary()


@app.get("/api/weekly")
async def get_weekly_summary(x_admin_api_key: str = Header(default="")):
    check_admin(x_admin_api_key)
    return journal.get_weekly_summary()


def create_system():
    """Create and initialize the trading system."""
    global system
    
    trader = AlpacaTrader()
    data_feed = DataFeed(trader)
    strategy = InstitutionalStrategy(trader, data_feed)
    
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    discord_notifier = DiscordNotifier(webhook_url) if webhook_url else None
    
    state = load_state()
    
    class TradingSystem:
        def __init__(self):
            self.status = "stopped"
            self.mode = "paper" if os.environ.get("PAPER_TRADING", "true") == "true" else "live"
            self.trader = trader
            self.data_feed = data_feed
            self.strategy = strategy
            self.state = state
            self.start_time = None
            self.pnl_curve = []
            self.last_curve_update = None
        
        def start(self):
            self.status = "running"
            self.start_time = datetime.utcnow()
            logger.info("Trading loop started")
        
        def stop(self):
            self.status = "stopped"
            logger.info("Trading loop stopped")
    
    system = TradingSystem()
    
    async def trading_loop():
        while True:
            try:
                if system.status == "running":
                    now = get_et_now()
                    
                    # Heartbeat every 5 minutes
                    if now.minute % 5 == 0 and now.second < 30:
                        positions = trader.get_positions()
                        account = trader.get_account()
                        if account:
                            equity = float(account.get('equity', 0))
                            last_equity = float(account.get('last_equity', equity))
                            daily_pnl = equity - last_equity
                            logger.info(f"Heartbeat: {now.strftime('%H:%M')} | Positions: {len(positions)} | PnL: ${daily_pnl:+.2f}")
                
                await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"Trading loop error: {e}")
                await asyncio.sleep(60)
    
    asyncio.create_task(trading_loop())
    
    if os.environ.get("AUTO_START_TRADING", "true").lower() == "true":
        system.start()
        logger.info("Auto-started trading loop")


@app.on_event("startup")
async def startup():
    create_system()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
