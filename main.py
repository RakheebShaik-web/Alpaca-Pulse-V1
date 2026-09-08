#!/usr/bin/env python3
"""
FastAPI server for the trading system.
Provides REST API for the dashboard and runs the strategy loop.
"""
import os
import asyncio
import logging
import secrets
from datetime import datetime, timedelta, time as dtime
from typing import Optional, List, Dict
from contextlib import asynccontextmanager
from functools import wraps

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import uvicorn

from config import config
from alpaca_trader import AlpacaTrader
from discord_notifier import DiscordNotifier
from models import (
    TradingStatus, SystemStatus, Position, TradeRecord,
    DailyStats, TradeSignal, FillResult, ScanResult
)

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
        # If no admin key is set, allow all requests (backward compatible)
        return True
    if not secrets.compare_digest(credentials.credentials, admin_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True

# ──────────────────────────────────────────────────────────────────────
# Global state
# ──────────────────────────────────────────────────────────────────────

class TradingState:
    def __init__(self):
        self._trader = None
        self._notifier = None
        self.status = TradingStatus.STOPPED
        self.mode = "paper"
        self.start_time = None
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.active_positions: Dict[str, dict] = {}
        self.trade_history: List[dict] = []
        self.daily_stats: List[dict] = []
        self.current_date = None
        self.or_high = None
        self.or_low = None
        self.pm_high = None
        self.pm_low = None
        self.pm_open = None
        self.prev_close = None
        self.todays_setups: List[dict] = []
    
    @property
    def trader(self) -> AlpacaTrader:
        """Lazy initialization of the trader."""
        if self._trader is None:
            self._trader = AlpacaTrader()
        return self._trader
    
    @property
    def notifier(self) -> DiscordNotifier:
        """Lazy initialization of the notifier."""
        if self._notifier is None:
            self._notifier = DiscordNotifier(os.getenv('DISCORD_WEBHOOK_URL', ''))
        return self._notifier
    
    def reset_daily(self, date):
        """Reset daily counters."""
        if date != self.current_date:
            if self.current_date is not None:
                self.notifier.send_daily_summary({
                    'date': str(self.current_date),
                    'trades': self.trades_today,
                    'win_rate': 0,
                    'daily_pnl': self.daily_pnl,
                    'portfolio': self.get_portfolio_value(),
                })
            self.current_date = date
            self.daily_pnl = 0.0
            self.trades_today = 0
            self.or_high = None
            self.or_low = None
            self.pm_high = None
            self.pm_low = None
            self.pm_open = None
            self.prev_close = None
            self.todays_setups = []
    
    def get_portfolio_value(self) -> float:
        """Get current portfolio value."""
        try:
            account = self.trader.get_account()
            return account['equity'] if account else 0.0
        except Exception:
            return 0.0
    
    def get_buying_power(self) -> float:
        """Get buying power."""
        try:
            account = self.trader.get_account()
            return account['buying_power'] if account else 0.0
        except Exception:
            return 0.0

state = TradingState()

# ──────────────────────────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app lifecycle."""
    logger.info("Trading system starting...")
    yield
    logger.info("Trading system shutting down...")

app = FastAPI(
    title="Pulse V1 Trading System",
    description="Automated trading system with real-time execution",
    version="1.0.0",
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

@app.get("/api/status", response_model=SystemStatus)
async def get_status():
    """Get system status (public read-only)."""
    uptime = 0.0
    if state.start_time:
        uptime = (datetime.utcnow() - state.start_time).total_seconds()
    
    return SystemStatus(
        status=state.status,
        mode=state.mode,
        uptime=uptime,
        daily_pnl=state.daily_pnl,
        total_trades=len(state.trade_history),
        active_positions=len(state.active_positions),
        portfolio_value=state.get_portfolio_value(),
        buying_power=state.get_buying_power(),
    )

@app.get("/api/positions", response_model=List[Position])
async def get_positions():
    """Get current positions (public read-only)."""
    positions = state.trader.get_positions()
    return [Position(
        symbol=p['symbol'],
        side=p['side'],
        entry=p['entry_price'],
        current_price=p['current_price'],
        size=p['qty'],
        stop=0.0,
        target=0.0,
        pnl=p['unrealized_pl'],
        pnl_pct=p['unrealized_plpc'],
        entry_time=datetime.utcnow(),
    ) for p in positions]

@app.get("/api/trades")
async def get_trades():
    """Get trade history (public read-only)."""
    return state.trade_history

@app.get("/api/daily")
async def get_daily_stats():
    """Get daily statistics (public read-only)."""
    return state.daily_stats

@app.get("/api/scan")
async def get_scan():
    """Get pre-market scan (public read-only)."""
    return state.todays_setups

@app.get("/api/clock")
async def get_clock():
    """Get market clock (public read-only)."""
    clock = state.trader.get_clock()
    if not clock:
        raise HTTPException(status_code=500, detail="Failed to fetch clock")
    return clock

@app.get("/api/account")
async def get_account():
    """Get account details (public read-only)."""
    account = state.trader.get_account()
    if not account:
        raise HTTPException(status_code=500, detail="Failed to fetch account")
    return account

# ─── Admin-only endpoints (require API key) ─────────────────────────

@app.post("/api/start")
async def start_trading(_=Depends(require_admin_key)):
    """Start the trading system (admin only)."""
    if state.status == TradingStatus.RUNNING:
        return {"status": "already_running"}
    
    state.status = TradingStatus.RUNNING
    state.mode = "paper" if state.trader.paper else "live"
    state.start_time = datetime.utcnow()
    
    # Start the trading loop in background
    asyncio.create_task(trading_loop())
    
    state.notifier.send(f"**Trading Started** | Mode: {state.mode.upper()}")
    return {"status": "started", "mode": state.mode}

@app.post("/api/stop")
async def stop_trading(_=Depends(require_admin_key)):
    """Stop the trading system."""
    state.status = TradingStatus.STOPPED
    state.notifier.send("**Trading Stopped**")
    return {"status": "stopped"}

@app.post("/api/close-all")
async def close_all(_=Depends(require_admin_key)):
    """Close all positions."""
    state.trader.close_all_positions()
    state.active_positions.clear()
    state.notifier.send("**All Positions Closed**")
    return {"status": "closed"}

@app.post("/api/cancel-all")
async def cancel_all(_=Depends(require_admin_key)):
    """Cancel all orders."""
    state.trader.cancel_all_orders()
    return {"status": "cancelled"}

@app.get("/api/price/{symbol}")
async def get_price(symbol: str):
    """Get latest price for a symbol."""
    price = state.trader.get_latest_price(symbol.upper())
    if price is None:
        raise HTTPException(status_code=404, detail="Price not found")
    return {"symbol": symbol.upper(), "price": price}

@app.get("/api/scan")
async def scan_setups():
    """Scan for pre-market setups."""
    setups = scan_for_setups()
    return setups

@app.get("/api/clock")
async def get_clock():
    """Get market clock."""
    clock = state.trader.get_clock()
    if not clock:
        raise HTTPException(status_code=500, detail="Failed to fetch clock")
    return clock

# ──────────────────────────────────────────────────────────────────────
# Trading Logic
# ──────────────────────────────────────────────────────────────────────

def scan_for_setups() -> List[dict]:
    """Scan for pre-market momentum setups."""
    setups = []
    now = datetime.now()
    
    # Only scan during pre-market hours
    if now.time() < dtime(4, 0) or now.time() >= dtime(9, 30):
        return setups
    
    for symbol in config.universe:
        try:
            bars = state.trader.get_bars(symbol, days=1)
            if bars is None or bars.empty:
                continue
            
            # Get previous close (from yesterday's last bar)
            prev_close = state.prev_close
            
            # Pre-market metrics
            pm_high = bars['high'].max()
            pm_low = bars['low'].min()
            pm_volume = int(bars['volume'].sum())
            pm_open = float(bars['open'].iloc[0])
            
            if prev_close and prev_close > 0:
                gap_pct = (pm_open - prev_close) / prev_close
                
                if abs(gap_pct) >= config.gap_threshold and pm_volume >= config.min_premarket_volume:
                    direction = "long" if gap_pct > 0 else "short"
                    score = abs(gap_pct) * pm_volume / 100000
                    
                    setups.append({
                        'symbol': symbol,
                        'direction': direction,
                        'gap_pct': gap_pct,
                        'pm_volume': pm_volume,
                        'pm_high': pm_high,
                        'pm_low': pm_low,
                        'score': score,
                    })
        except Exception as e:
            logger.debug(f"Scan error for {symbol}: {e}")
    
    # Sort by score
    setups.sort(key=lambda x: x['score'], reverse=True)
    return setups

async def trading_loop():
    """Main trading loop."""
    logger.info("Trading loop started")
    
    while state.status == TradingStatus.RUNNING:
        try:
            now = datetime.now()
            state.reset_daily(now.date())
            current_time = now.time()
            
            # Check if market is open
            if not state.trader.is_market_open():
                await asyncio.sleep(60)
                continue
            
            # === PRE-MARKET: Track range ===
            if dtime(4, 0) <= current_time < dtime(9, 30):
                # Scan for setups once per hour
                if now.minute < 5:
                    state.todays_setups = scan_for_setups()
                    if state.todays_setups:
                        state.notifier.send_scan_results(state.todays_setups)
                await asyncio.sleep(30)
                continue
            
            # === OPENING RANGE: Build OR ===
            if dtime(9, 30) <= current_time < dtime(9, 45):
                # Track opening range
                for symbol in config.universe:
                    price = state.trader.get_latest_price(symbol)
                    if price:
                        if state.or_high is None:
                            state.or_high = price
                            state.or_low = price
                        else:
                            state.or_high = max(state.or_high, price)
                            state.or_low = min(state.or_low, price)
                await asyncio.sleep(30)
                continue
            
            # === TRADING HOURS: Execute ===
            if dtime(9, 45) <= current_time < config.trading_end:
                # Check daily limits
                if state.trades_today >= config.max_trades_per_day:
                    await asyncio.sleep(60)
                    continue
                if state.daily_pnl <= -config.max_daily_loss:
                    await asyncio.sleep(60)
                    continue
                if state.daily_pnl >= config.target_daily_pnl:
                    await asyncio.sleep(60)
                    continue
                
                # Execute setups
                if state.todays_setups and not state.active_positions:
                    for setup in state.todays_setups[:3]:  # Top 3
                        symbol = setup['symbol']
                        
                        # Skip if already in position
                        if state.trader.get_position(symbol):
                            continue
                        
                        # Get current price
                        price = state.trader.get_latest_price(symbol)
                        if not price:
                            continue
                        
                        # Calculate entry, stop, target
                        direction = setup['direction']
                        if direction == 'long':
                            entry = price
                            stop = entry * 0.995
                            risk = entry - stop
                            target = entry + (risk * config.rr_ratio)
                        else:
                            entry = price
                            stop = entry * 1.005
                            risk = stop - entry
                            target = entry - (risk * config.rr_ratio)
                        
                        # Calculate position size
                        size = max(1, int(config.risk_per_trade / risk))
                        
                        # Submit bracket order
                        result = state.trader.submit_bracket_order(
                            symbol=symbol,
                            qty=size,
                            side=SignalSide.BUY if direction == 'long' else SignalSide.SELL,
                            stop_price=round(stop, 2),
                            target_price=round(target, 2),
                        )
                        
                        if result:
                            state.trades_today += 1
                            state.active_positions[symbol] = {
                                'side': direction,
                                'entry': entry,
                                'stop': stop,
                                'target': target,
                                'size': size,
                            }
                            
                            # Discord alert
                            state.notifier.send_trade_alert({
                                'symbol': symbol,
                                'direction': direction.upper(),
                                'entry': entry,
                                'stop': stop,
                                'target': target,
                                'size': size,
                                'risk': risk * size,
                                'gap_pct': setup['gap_pct'],
                            })
                
                await asyncio.sleep(30)
                continue
            
            # === POST-TRADE: Close all at 3:50 PM ===
            if current_time >= config.trading_end:
                if state.active_positions:
                    state.trader.close_all_positions()
                    state.active_positions.clear()
                await asyncio.sleep(60)
                continue
            
            await asyncio.sleep(30)
            
        except Exception as e:
            logger.error(f"Trading loop error: {e}")
            await asyncio.sleep(60)
    
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
