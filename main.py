#!/usr/bin/env python3
"""
FastAPI server for the trading system.
Provides REST API for the dashboard and runs the strategy loop.
Institutional-grade with multi-timeframe analysis and crash-safe persistence.
"""
import os
import asyncio
import logging
import secrets
from datetime import datetime, timedelta, time as dtime
from typing import Optional, List, Dict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import uvicorn

from config import config
from alpaca_trader import AlpacaTrader
from discord_notifier import DiscordNotifier
from state_store import BotState, TradePosition, load_state, save_state, new_position
from data_feed import DataFeed
from strategy import Strategy, Signal, SignalDirection
from csv_log import log_trade, get_trade_summary

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Authentication
# ──────────────────────────────────────────────────────────────────────

security = HTTPBearer()

def require_admin_key(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify admin API key for protected endpoints."""
    admin_key = os.getenv('ADMIN_API_KEY')
    if not admin_key:
        return True
    provided = credentials.credentials.strip().lower()
    expected = admin_key.strip().lower()
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True

# ──────────────────────────────────────────────────────────────────────
# Global state
# ──────────────────────────────────────────────────────────────────────

class TradingSystem:
    def __init__(self):
        self.trader = AlpacaTrader()
        self.data_feed = DataFeed(self.trader)
        self.strategy = Strategy(self.data_feed)
        self.notifier = DiscordNotifier(os.getenv('DISCORD_WEBHOOK_URL', ''))
        self.state = BotState()
        self.status = "stopped"
        self.mode = "paper"
        self.start_time = None
        self._trading_task = None
        self._previous_closes: Dict[str, float] = {}
    
    def get_portfolio_value(self) -> float:
        try:
            account = self.trader.get_account()
            return account['equity'] if account else 0.0
        except:
            return 0.0
    
    def get_buying_power(self) -> float:
        try:
            account = self.trader.get_account()
            return account['buying_power'] if account else 0.0
        except:
            return 0.0

system = TradingSystem()

# ──────────────────────────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app lifecycle."""
    logger.info("Trading system starting...")
    
    # Load persisted state
    system.state = load_state()
    
    yield
    
    # Save state on shutdown
    save_state(system.state)
    logger.info("Trading system shutting down...")

app = FastAPI(
    title="Pulse V1 Trading System",
    description="Automated trading system with multi-timeframe analysis",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────────────────────────────
# API Endpoints
# ──────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    """Health check."""
    return {"status": "ok", "service": "Pulse V1 Trading System"}

@app.get("/api/status")
async def get_status():
    """Get system status (public read-only)."""
    uptime = 0.0
    if system.start_time:
        uptime = (datetime.utcnow() - system.start_time).total_seconds()
    
    return {
        "status": system.status,
        "mode": system.mode,
        "uptime": uptime,
        "daily_pnl": system.state.daily_pnl,
        "total_trades": system.state.trades_today,
        "active_positions": len(system.state.all_positions()),
        "portfolio_value": system.get_portfolio_value(),
        "buying_power": system.get_buying_power(),
    }

@app.get("/api/positions")
async def get_positions():
    """Get current positions (public read-only)."""
    positions = system.trader.get_positions()
    return [{
        "symbol": p['symbol'],
        "side": p['side'],
        "entry": p['entry_price'],
        "current_price": p['current_price'],
        "size": p['qty'],
        "pnl": p['unrealized_pl'],
        "pnl_pct": p['unrealized_plpc'],
    } for p in positions]

@app.get("/api/trades")
async def get_trades():
    """Get trade history (public read-only)."""
    return get_trade_summary()

@app.get("/api/scan")
async def get_scan():
    """Get latest signals (public read-only)."""
    return system.state.todays_setups if hasattr(system.state, 'todays_setups') else []

@app.get("/api/clock")
async def get_clock():
    """Get market clock (public read-only)."""
    clock = system.trader.get_clock()
    if not clock:
        raise HTTPException(status_code=500, detail="Failed to fetch clock")
    return clock

@app.get("/api/account")
async def get_account():
    """Get account details (public read-only)."""
    account = system.trader.get_account()
    if not account:
        raise HTTPException(status_code=500, detail="Failed to fetch account")
    return account

# ─── Admin-only endpoints (require API key) ─────────────────────────

@app.post("/api/start")
async def start_trading(_=Depends(require_admin_key)):
    """Start the trading system (admin only)."""
    if system.status == "running":
        if system._trading_task and not system._trading_task.done():
            return {"status": "already_running"}
        logger.warning("Loop was marked RUNNING but task is dead, restarting...")
    
    system.status = "running"
    system.mode = "paper" if system.trader.paper else "live"
    system.start_time = datetime.utcnow()
    system._trading_task = asyncio.create_task(trading_loop())
    
    system.notifier.send(f"**Trading Started** | Mode: {system.mode.upper()}")
    return {"status": "started", "mode": system.mode}

@app.post("/api/stop")
async def stop_trading(_=Depends(require_admin_key)):
    """Stop the trading system."""
    system.status = "stopped"
    system.notifier.send("**Trading Stopped**")
    return {"status": "stopped"}

@app.post("/api/close-all")
async def close_all(_=Depends(require_admin_key)):
    """Close all positions."""
    system.trader.close_all_positions()
    system.state.positions.clear()
    save_state(system.state)
    system.notifier.send("**All Positions Closed**")
    return {"status": "closed"}

@app.post("/api/cancel-all")
async def cancel_all(_=Depends(require_admin_key)):
    """Cancel all orders."""
    system.trader.cancel_all_orders()
    return {"status": "cancelled"}

# ──────────────────────────────────────────────────────────────────────
# Trading Loop
# ──────────────────────────────────────────────────────────────────────

async def trading_loop():
    """Main trading loop."""
    logger.info("Trading loop started")
    
    # Load persisted state
    system.state = load_state()
    
    while system.status == "running":
        try:
            now = datetime.now()
            current_time = now.time()
            
            # Log heartbeat every 5 minutes
            if now.minute % 5 == 0 and now.second < 30:
                logger.info(
                    f"Heartbeat: {now.strftime('%H:%M')} | "
                    f"Positions: {len(system.state.all_positions())} | "
                    f"PnL: ${system.state.daily_pnl:+.2f}"
                )
            
            # Check if market is open
            try:
                if not system.trader.is_market_open():
                    await asyncio.sleep(60)
                    continue
            except Exception as e:
                logger.warning(f"Market check failed: {e}")
                await asyncio.sleep(60)
                continue
            
            # === PRE-MARKET: Scan for signals ===
            if dtime(4, 0) <= current_time < dtime(9, 30):
                if now.minute < 5:
                    try:
                        signals = system.strategy.generate_all_signals()
                        if signals:
                            system.notifier.send_scan_results([
                                {
                                    "symbol": s.symbol,
                                    "direction": s.direction.value,
                                    "gap_pct": 0.0,
                                    "pm_volume": 0,
                                    "score": 0.0,
                                } for s in signals
                            ])
                    except Exception as e:
                        logger.error(f"Scan error: {e}")
                await asyncio.sleep(30)
                continue
            
            # === OPENING RANGE: Build OR ===
            if dtime(9, 30) <= current_time < dtime(9, 45):
                await asyncio.sleep(30)
                continue
            
            # === TRADING HOURS: Execute ===
            if dtime(9, 45) <= current_time < config.trading_end:
                # Check daily limits
                if system.state.trades_today >= config.max_trades_per_day:
                    await asyncio.sleep(60)
                    continue
                if system.state.daily_pnl <= -config.max_daily_loss:
                    await asyncio.sleep(60)
                    continue
                if system.state.daily_pnl >= config.target_daily_pnl:
                    await asyncio.sleep(60)
                    continue
                
                # Check consecutive losses
                if system.state.consecutive_losses >= config.max_consecutive_losses:
                    await asyncio.sleep(60)
                    continue
                
                # Generate and execute signals
                signals = system.strategy.generate_all_signals()
                for signal in signals:
                    try:
                        # Check if already in position
                        if signal.symbol in system.state.positions:
                            continue
                        
                        # Calculate position size
                        atr = signal.atr
                        stop_distance = atr * config.atr_stop_multiplier
                        size = max(1, int(config.risk_per_trade / stop_distance))
                        max_size = int(config.capital * config.max_position_pct / signal.price)
                        size = min(size, max_size)
                        
                        # Submit bracket order
                        result = system.trader.submit_bracket_order(
                            symbol=signal.symbol,
                            qty=size,
                            side=SignalDirection.LONG if signal.direction == SignalDirection.LONG else SignalDirection.SELL,
                            stop_price=signal.stop,
                            target_price=signal.target,
                        )
                        
                        if result:
                            system.state.trades_today += 1
                            
                            # Create position record
                            position = new_position(
                                symbol=signal.symbol,
                                side=signal.direction.value,
                                entry_price=signal.price,
                                shares=size,
                                stop_price=signal.stop,
                                target_price=signal.target,
                            )
                            system.state.add_position(position)
                            
                            # Log trade
                            log_trade(
                                symbol=signal.symbol,
                                side=signal.direction.value,
                                entry_price=signal.price,
                                shares=size,
                                stop_price=signal.stop,
                                target_price=signal.target,
                                status="open",
                                notes=f"pos_id={position.position_id}",
                            )
                            
                            # Send alert
                            system.notifier.send_trade_alert({
                                "symbol": signal.symbol,
                                "direction": signal.direction.value.upper(),
                                "entry": signal.price,
                                "stop": signal.stop,
                                "target": signal.target,
                                "size": size,
                                "risk": stop_distance * size,
                                "gap_pct": 0.0,
                            })
                            
                            # Save state
                            save_state(system.state)
                            
                    except Exception as e:
                        logger.error(f"Trade execution error: {e}")
                
                await asyncio.sleep(30)
                continue
            
            # === POST-TRADE: Close all at 3:50 PM ===
            if current_time >= config.trading_end:
                if system.state.positions:
                    system.trader.close_all_positions()
                    system.state.positions.clear()
                    save_state(system.state)
                await asyncio.sleep(60)
                continue
            
            await asyncio.sleep(30)
            
        except asyncio.CancelledError:
            logger.info("Trading loop cancelled")
            break
        except Exception as e:
            logger.error(f"Trading loop error: {e}", exc_info=True)
            await asyncio.sleep(30)
    
    logger.info("Trading loop stopped")

# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
