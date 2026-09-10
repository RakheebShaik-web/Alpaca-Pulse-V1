#!/usr/bin/env python3
"""
FastAPI server for the trading system.
Institutional Footprint Strategy — multi-factor alpha generation.
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
import uvicorn

from config import config
from alpaca_trader import AlpacaTrader
from discord_notifier import DiscordNotifier
from state_store import BotState, TradePosition, load_state, save_state, new_position
from data_feed import DataFeed
from institutional_strategy import InstitutionalStrategy, Signal, SignalDirection, Position
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
    """Verify admin API key."""
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
        self.strategy = InstitutionalStrategy(self.data_feed)
        self.notifier = DiscordNotifier(os.getenv('DISCORD_WEBHOOK_URL', ''))
        self.state = BotState()
        self.status = "stopped"
        self.mode = "paper"
        self.start_time = None
        self._trading_task = None
    
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
    logger.info("Trading system starting...")
    system.state = load_state()
    yield
    save_state(system.state)
    logger.info("Trading system shutting down...")

app = FastAPI(
    title="Pulse V1 — Institutional Footprint",
    description="Multi-factor alpha generation strategy",
    version="3.0.0",
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
    return {"status": "ok", "service": "Pulse V1 — Institutional Footprint"}

@app.get("/api/status")
async def get_status():
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
    return get_trade_summary()

@app.get("/api/daily")
async def get_daily_stats():
    return get_trade_summary()

@app.get("/api/scan")
async def get_scan():
    return []

@app.get("/api/clock")
async def get_clock():
    clock = system.trader.get_clock()
    if not clock:
        raise HTTPException(status_code=500, detail="Failed to fetch clock")
    return clock

@app.get("/api/account")
async def get_account():
    account = system.trader.get_account()
    if not account:
        raise HTTPException(status_code=500, detail="Failed to fetch account")
    return account

# ─── Admin-only endpoints ─────────────────────────────────────────

@app.post("/api/start")
async def start_trading(_=Depends(require_admin_key)):
    if system.status == "running":
        if system._trading_task and not system._trading_task.done():
            return {"status": "already_running"}
    
    system.status = "running"
    system.mode = "paper" if system.trader.paper else "live"
    system.start_time = datetime.utcnow()
    system._trading_task = asyncio.create_task(trading_loop())
    
    system.notifier.send(f"**Trading Started** | Mode: {system.mode.upper()}")
    return {"status": "started", "mode": system.mode}

@app.post("/api/stop")
async def stop_trading(_=Depends(require_admin_key)):
    system.status = "stopped"
    system.notifier.send("**Trading Stopped**")
    return {"status": "stopped"}

@app.post("/api/close-all")
async def close_all(_=Depends(require_admin_key)):
    system.trader.close_all_positions()
    system.state.positions.clear()
    save_state(system.state)
    system.notifier.send("**All Positions Closed**")
    return {"status": "closed"}

@app.post("/api/cancel-all")
async def cancel_all(_=Depends(require_admin_key)):
    system.trader.cancel_all_orders()
    return {"status": "cancelled"}

# ──────────────────────────────────────────────────────────────────────
# Trading Loop
# ──────────────────────────────────────────────────────────────────────

async def sync_positions_on_startup():
    """Sync with Alpaca on startup."""
    try:
        positions = system.trader.get_positions()
        if positions:
            logger.info(f"Found {len(positions)} open position(s) on startup")
            for p in positions:
                position = new_position(
                    symbol=p['symbol'],
                    side=p['side'],
                    entry_price=p['entry_price'],
                    shares=p['qty'],
                    stop_price=p['entry_price'] * 0.995,
                    target_price=p['entry_price'] * 1.01,
                )
                system.state.add_position(position)
        else:
            logger.info("No open positions on startup")
    except Exception as e:
        logger.error(f"Position sync failed: {e}")


async def trading_loop():
    """Main trading loop — Institutional Footprint Strategy."""
    logger.info("Trading loop started")
    
    system.state = load_state()
    await sync_positions_on_startup()
    
    while system.status == "running":
        try:
            now = datetime.now()
            current_time = now.time()
            
            # Heartbeat every 5 minutes
            if now.minute % 5 == 0 and now.second < 30:
                logger.info(
                    f"Heartbeat: {now.strftime('%H:%M')} | "
                    f"Positions: {len(system.state.all_positions())} | "
                    f"PnL: ${system.state.daily_pnl:+.2f}"
                )
            
            # Check market open
            try:
                if not system.trader.is_market_open():
                    await asyncio.sleep(60)
                    continue
            except Exception as e:
                logger.warning(f"Market check failed: {e}")
                await asyncio.sleep(60)
                continue
            
            # === EXECUTION WINDOW ONLY ===
            if not system.strategy.is_execution_window():
                await asyncio.sleep(60)
                continue
            
            # === CHECK LIMITS ===
            if system.state.trades_today >= config.max_trades_per_day:
                await asyncio.sleep(60)
                continue
            if system.state.daily_pnl <= -config.max_daily_loss:
                await asyncio.sleep(60)
                continue
            if system.state.consecutive_losses >= config.max_consecutive_losses:
                await asyncio.sleep(60)
                continue
            
            # === CHECK MAX DRAWDOWN ===
            current_equity = system.get_portfolio_value()
            if system.strategy.check_max_drawdown(current_equity):
                logger.critical("Max drawdown exceeded! Halting trading.")
                system.notifier.send("**TRADING HALTED** — Max drawdown exceeded")
                await asyncio.sleep(300)
                continue
            
            # === UPDATE POSITIONS (trailing stops, exits) ===
            for symbol in list(system.strategy.positions.keys()):
                try:
                    price = system.data_feed.get_latest_price(symbol)
                    if not price:
                        continue
                    
                    position = system.strategy.positions[symbol]
                    atr = system.data_feed.get_atr(symbol, config.atr_length) or (price * 0.005)
                    
                    # Update trailing stop
                    position.update_trailing_stop(price, atr)
                    
                    # Check for exit
                    should_exit, reason = position.should_exit(price)
                    if should_exit:
                        # Close on Alpaca
                        system.trader.close_position(symbol)
                        
                        # Calculate PnL
                        if position.direction == SignalDirection.LONG:
                            pnl = (price - position.entry_price) * position.shares
                        else:
                            pnl = (position.entry_price - price) * position.shares
                        
                        # Update state
                        system.state.daily_pnl += pnl
                        system.state.consecutive_losses = system.state.consecutive_losses + 1 if pnl < 0 else 0
                        
                        # Log to CSV
                        log_trade(
                            symbol=symbol,
                            side=position.direction.value,
                            entry_price=position.entry_price,
                            exit_price=price,
                            shares=position.shares,
                            stop_price=position.stop,
                            target_price=position.target,
                            pnl=pnl,
                            exit_reason=reason,
                            status="closed",
                        )
                        
                        # Remove from tracking
                        system.strategy.close_position(symbol)
                        save_state(system.state)
                        
                        # Notify
                        system.notifier.send_trade_alert({
                            'symbol': symbol,
                            'direction': 'CLOSED',
                            'entry': position.entry_price,
                            'exit_price': price,
                            'pnl': pnl,
                            'reason': reason,
                        })
                        
                        logger.info(f"Position closed: {symbol} PnL=${pnl:.2f} Reason={reason}")
                except Exception as e:
                    logger.error(f"Position update error for {symbol}: {e}")
            
            # === GENERATE SIGNALS ===
            signals = system.strategy.generate_all_signals()
            
            # Limit to 3 total positions (including existing)
            open_count = len(system.strategy.positions)
            if open_count >= 3:
                await asyncio.sleep(30)
                continue
            
            max_new = 3 - open_count
            for signal in signals[:max_new]:
                try:
                    symbol = signal.symbol
                    
                    # Skip if already in position
                    if symbol in system.strategy.positions:
                        continue
                    
                    # Check sector exposure
                    if not system.strategy.check_sector_exposure(symbol):
                        continue
                    
                    # Calculate position size — exactly $50 risk per trade
                    stop_distance = abs(signal.price - signal.stop)
                    if stop_distance <= 0:
                        continue
                    size = max(1, int(config.risk_per_trade / stop_distance))
                    max_size = int(config.capital * config.max_position_pct / signal.price)
                    size = min(size, max_size)
                    
                    # Submit bracket order
                    result = system.trader.submit_bracket_order(
                        symbol=symbol,
                        qty=size,
                        side=SignalDirection.LONG if signal.direction == SignalDirection.LONG else SignalDirection.SELL,
                        stop_price=signal.stop,
                        target_price=signal.target,
                    )
                    
                    if result:
                        system.state.trades_today += 1
                        
                        # Add to strategy positions
                        system.strategy.add_position(
                            symbol=symbol,
                            direction=signal.direction,
                            price=signal.price,
                            shares=size,
                            stop=signal.stop,
                            target=signal.target,
                        )
                        
                        # Create position record
                        position = new_position(
                            symbol=symbol,
                            side=signal.direction.value,
                            entry_price=signal.price,
                            shares=size,
                            stop_price=signal.stop,
                            target_price=signal.target,
                        )
                        system.state.add_position(position)
                        
                        # Log trade
                        log_trade(
                            symbol=symbol,
                            side=signal.direction.value,
                            entry_price=signal.price,
                            shares=size,
                            stop_price=signal.stop,
                            target_price=signal.target,
                            status="open",
                            notes=f"score={signal.score} pos_id={position.position_id}",
                        )
                        
                        # Send alert
                        system.notifier.send_trade_alert({
                            'symbol': symbol,
                            'direction': signal.direction.value.upper(),
                            'entry': signal.price,
                            'stop': signal.stop,
                            'target': signal.target,
                            'size': size,
                            'risk': stop_distance * size,
                            'gap_pct': signal.vwap_deviation,
                        })
                        
                        # Save state
                        save_state(system.state)
                        
                except Exception as e:
                    logger.error(f"Trade execution error: {e}")
            
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
