#!/usr/bin/env python3
"""
FastAPI server for the trading system.
Institutional Footprint Strategy — multi-factor alpha generation.
"""
import os
import asyncio
import logging
import secrets
from datetime import datetime, time as dtime, timedelta
from typing import Optional, List, Dict, Any

import uvicorn
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pytz

from config import config
from discord_notifier import DiscordNotifier
from state_store import BotState, TradePosition, load_state, save_state, new_position
from data_feed import DataFeed
from institutional_strategy import InstitutionalStrategy, Signal, SignalDirection, Position, get_et_now, get_et_time
from csv_log import log_trade, get_trade_summary
from trade_journal import journal
from earnings_filter import earnings_filter
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
discord_notifier = None


def require_admin_key():
    """Dependency to require admin API key."""
    from fastapi import Header
    def _check(x_admin_api_key: str = Header(default="")):
        if x_admin_api_key.lower() != os.environ.get("ADMIN_API_KEY", "").lower():
            raise HTTPException(status_code=401, detail="Not authenticated")
    return _check


@app.get("/")
async def root():
    return {"status": "ok", "service": "Pulse V1 — Institutional Footprint"}


@app.get("/api/status")
async def get_status(_=Depends(require_admin_key)):
    uptime = 0.0
    if system and system.start_time:
        uptime = (datetime.utcnow() - system.start_time).total_seconds()
    
    account = system.trader.get_account() if system and system.trader else None
    equity = float(account.get('equity', 0)) if account else 0
    last_equity = float(account.get('last_equity', equity)) if account else equity
    
    return {
        "status": system.status if system else "stopped",
        "mode": "paper" if os.environ.get("PAPER_TRADING", "true") == "true" else "live",
        "uptime": uptime,
        "daily_pnl": round(equity - last_equity, 2),
        "total_trades": system.state.trades_today if system else 0,
        "active_positions": len(system.state.all_positions()) if system else 0,
        "portfolio_value": round(equity, 2),
        "buying_power": round(float(account.get('buying_power', 0)), 2) if account else 0,
        "reconciliation_error": runtime.error if 'runtime' in globals() else None,
        "last_scan_at": runtime.last_scan_at if 'runtime' in globals() else None,
        "last_scan_error": runtime.last_scan_error if 'runtime' in globals() else None,
    }


@app.get("/api/positions")
async def get_positions(_=Depends(require_admin_key)):
    """Get open positions with SL/TP1/TP2 levels."""
    if not system or not system.trader:
        return []
    
    positions = system.trader.get_positions()
    result = []
    for p in positions:
        entry = p.get('entry_price', 0)
        current = p.get('current_price', 0)
        qty = p.get('qty', 0)
        side = p.get('side', 'long')
        
        # Calculate SL/TP1/TP2
        risk_per_share = config.risk_per_trade / qty if qty > 0 else 0
        if side == 'long':
            sl = round(entry - risk_per_share, 2)
            tp1 = round(entry + risk_per_share * 0.8, 2)  # 0.8R
            tp2 = round(entry + risk_per_share * 1.5, 2)  # 1.5R
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
async def get_trades(_=Depends(require_admin_key)):
    """Get trade summary with win rate and P&L."""
    return get_trade_summary()


@app.get("/api/closed-positions")
async def get_closed_positions(_=Depends(require_admin_key)):
    """Get closed positions stats."""
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
async def get_pnl_curve(_=Depends(require_admin_key)):
    """Get today's PnL curve data."""
    if not system:
        return []
    return system.pnl_curve


@app.get("/api/prior-day")
async def get_prior_day(_=Depends(require_admin_key)):
    """Compare today to prior trading day."""
    if not system:
        return {"win_rate_change": 0, "pnl_change": 0, "trade_count_change": 0}
    return system.prior_day_stats


@app.get("/api/symbol-stats")
async def get_symbol_stats(_=Depends(require_admin_key)):
    """Get per-symbol statistics."""
    if not system:
        return []
    return system.symbol_stats


@app.get("/api/trade-logs")
async def get_trade_logs(_=Depends(require_admin_key)):
    """Get recent trade logs."""
    if not system or not system.trader:
        return []
    
    orders = system.trader.get_orders(status="closed")
    logs = []
    for o in orders[:50]:  # Last 50
        logs.append({
            "time": o.get('filled_at', o.get('submitted_at', '')).isoformat() if o.get('filled_at') or o.get('submitted_at') else '',
            "symbol": o.get('symbol', ''),
            "event": o.get('type', '').upper(),
            "side": o.get('side', ''),
            "price": o.get('filled_avg_price', 0),
            "shares": o.get('filled_qty', 0),
            "pnl": o.get('pnl', 0),
        })
    return logs


@app.get("/api/daily")
async def get_daily_stats(_=Depends(require_admin_key)):
    return get_trade_summary()


@app.get("/api/weekly")
async def get_weekly_summary(_=Depends(require_admin_key)):
    return journal.get_weekly_summary()


@app.get("/api/journal")
async def get_journal(_=Depends(require_admin_key)):
    return journal.get_summary()


@app.get("/api/clock")
async def get_clock(_=Depends(require_admin_key)):
    now = get_et_now()
    return {
        "time": now.strftime("%I:%M:%S %p ET"),
        "date": now.strftime("%m/%d/%Y"),
        "market_open": (config.morning_window_start <= now.time() <= config.trading_end),
    }


@app.post("/api/start")
async def start_bot(_=Depends(require_admin_key)):
    global system
    if system and system.status == "running":
        return {"status": "already running"}
    if system:
        system.start()
    return {"status": "started"}


@app.post("/api/stop")
async def stop_bot(_=Depends(require_admin_key)):
    global system
    if system:
        system.stop()
    return {"status": "stopped"}


@app.post("/api/close-all")
async def close_all(_=Depends(require_admin_key)):
    if system and system.trader:
        system.trader.close_all_positions()
    return {"status": "closing all"}


@app.post("/api/cancel-all")
async def cancel_all(_=Depends(require_admin_key)):
    if system and system.trader:
        system.trader.cancel_all_orders()
    return {"status": "cancelling all"}


def create_system():
    """Create and initialize the trading system."""
    global system, discord_notifier
    
    trader = AlpacaTrader()
    data_feed = DataFeed()
    strategy = InstitutionalStrategy(trader, data_feed)
    discord_notifier = DiscordNotifier()
    
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
            self.prior_day_stats = {"win_rate_change": 0, "pnl_change": 0, "trade_count_change": 0}
            self.symbol_stats = []
            self.last_curve_update = None
            self.peak_pnl = 0
        
        def start(self):
            self.status = "running"
            self.start_time = datetime.utcnow()
            logger.info("Trading loop started")
        
        def stop(self):
            self.status = "stopped"
            logger.info("Trading loop stopped")
        
        def get_portfolio_value(self):
            account = self.trader.get_account()
            return float(account.get('equity', 0)) if account else 0
        
        def get_buying_power(self):
            account = self.trader.get_account()
            return float(account.get('buying_power', 0)) if account else 0
        
        def record_pnl(self):
            """Record PnL for curve."""
            now = get_et_now()
            if now.time() < config.morning_window_start or now.time() > config.trading_end:
                return
            
            # Record every 5 minutes
            if (self.last_curve_update and 
                (now - self.last_curve_update).total_seconds() < 300):
                return
            
            account = self.trader.get_account()
            if not account:
                return
            
            equity = float(account.get('equity', 0))
            last_equity = float(account.get('last_equity', equity))
            unrealized = sum(p.get('unrealized_pl', 0) for p in self.trader.get_positions())
            daily_pnl = (equity - last_equized) + unrealized
            
            self.pnl_curve.append({
                "time": now.strftime("%H:%M"),
                "pnl": round(daily_pnl, 2),
                "timestamp": now.isoformat(),
            })
            self.last_curve_update = now
    
    system = TradingSystem()
    
    # Trading loop
    async def trading_loop():
        while True:
            try:
                if system.status == "running":
                    now = get_et_now()
                    current_time = now.time()
                    
                    # Heartbeat every 5 minutes
                    if now.minute % 5 == 0:
                        positions = trader.get_positions()
                        account = trader.get_account()
                        equity = float(account.get('equity', 0)) if account else 0
                        last_equity = float(account.get('last_equity', equity)) if account else equity
                        daily_pnl = equity - last_equity
                        logger.info(f"He heartbeat: {now.strftime('%H:%M')} | Positions: {len(positions)} | PnL: ${daily_pnl:+.2f}")
                        
                        # Record PnL curve
                        system.record_pnl()
                    
                    # Update position details
                    for pos in positions:
                        symbol = pos.get('symbol')
                        if symbol:
                            try:
                                price = data_feed.get_latest_price_yfinance(symbol)
                                if price:
                                    # Check trailing stops
                                    system.strategy.update_trailing_stops(symbol, price)
                            except Exception as e:
                                logger.debug(f"Position update failed for {symbol}: {e}")
                    
                    # Scan for new setups
                    if (config.morning_window_start <= current_time <= config.morning_window_end or
                        config.afternoon_window_start <= current_time <= config.afternoon_window_end):
                        
                        for symbol in config.universe:
                            try:
                                # Skip if already in position
                                if any(p.get('symbol') == symbol for p in positions):
                                    continue
                                
                                # Skip if max positions reached
                                if len(positions) >= config.max_trades_per_day:
                                    break
                                
                                signal = strategy.generate_signal(symbol)
                                if signal and signal.score >= config.min_score_to_trade:
                                    # Execute trade
                                    success = await execute_trade(signal)
                                    if success:
                                        positions = trader.get_positions()  # Refresh
                            except Exception as e:
                                logger.debug(f"Scan failed for {symbol}: {e}")
                
                await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"Trading loop error: {e}", exc_info=True)
                await asyncio.sleep(60)
    
    async def execute_trade(signal):
        """Execute a trade based on signal."""
        try:
            account = trader.get_account()
            if not account:
                return False
            
            buying_power = float(account.get('buying_power', 0))
            equity = float(account.get('equity', 0))
            
            # Position sizing
            risk_amount = config.risk_per_trade
            if signal.stop_distance > 0:
                shares = int(risk_amount / signal.stop_distance)
            else:
                shares = 0
            
            if shares <= 0:
                return False
            
            max_value = equity * config.max_position_pct
            price = signal.price or data_feed.get_latest_price_yfinance(signal.symbol)
            if not price or price * shares > max_value:
                shares = int(max_value / price) if price else 0
            
            if shares <= 0:
                return False
            
            # Submit order
            if signal.direction == SignalDirection.LONG:
                order = trader.submit_market_order(signal.symbol, shares, "buy")
            else:
                order = trader.submit_market_order(signal.symbol, shares, "sell")
            
            if order:
                log_trade(
                    symbol=signal.symbol,
                    side=signal.direction.value,
                    entry_price=price,
                    shares=shares,
                    stop_price=signal.stop,
                    target_price=signal.target,
                    notes=f"Score: {signal.score}/8"
                )
                
                journal.add_entry(
                    symbol=signal.symbol,
                    side=signal.direction.value,
                    entry_price=price,
                    shares=shares,
                    stop_price=signal.stop,
                    target_price=signal.target,
                    score=signal.score,
                    setup="; ".join(signal.factors),
                    regime="trending"
                )
                
                if discord_notifier:
                    discord_notifier.send_trade_alert(
                        symbol=signal.symbol,
                        side=signal.direction.value,
                        price=price,
                        shares=shares,
                        stop=signal.stop,
                        target=signal.target,
                        score=signal.score,
                        pnl=None
                    )
                
                return True
        except Exception as e:
            logger.error(f"Trade execution failed: {e}")
        return False
    
    asyncio.create_task(trading_loop())
    
    # Auto-start
    if os.environ.get("AUTO_START_TRADING", "true").lower() == "true":
        system.start()
        logger.info("Auto-started trading loop")


@app.on_event("startup")
async def startup():
    create_system()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
