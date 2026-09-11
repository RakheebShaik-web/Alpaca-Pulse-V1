#!/usr/bin/env python3
"""
FastAPI server for the trading system.
Institutional Footprint Strategy — multi-factor alpha generation.
"""
import os
import asyncio
import logging
import secrets
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import uvicorn

from alpaca_trader import AlpacaTrader
from discord_notifier import DiscordNotifier
from state_store import BotState, load_state, save_state
from data_feed import DataFeed
from institutional_strategy import InstitutionalStrategy, get_et_now
from csv_log import log_trade, get_trade_summary
from trade_journal import journal
from earnings_filter import earnings_filter
from trading_runtime import TradingRuntime

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
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY is not configured")
    provided = credentials.credentials
    expected = admin_key
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
    if system.trader.api_key and system.trader.secret_key:
        runtime.reconcile()
    system._trading_task = asyncio.create_task(trading_loop())
    yield
    system._trading_task.cancel()
    try:
        await system._trading_task
    except asyncio.CancelledError:
        pass
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
        "reconciliation_error": runtime.error,
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

@app.get("/api/weekly")
async def get_weekly_summary():
    return journal.get_weekly_summary()

@app.get("/api/journal")
async def get_journal():
    return journal.get_summary()

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
    if runtime.close_requested and system.state.all_positions():
        raise HTTPException(status_code=409, detail="Close-all is still pending")
    runtime.close_requested = False
    runtime.reconcile()
    if not runtime.ready:
        raise HTTPException(status_code=503, detail=runtime.error)
    system.status = "running"
    system.mode = "paper" if system.trader.paper else "live"
    system.start_time = datetime.utcnow()
    if not system._trading_task or system._trading_task.done():
        system._trading_task = asyncio.create_task(trading_loop())
    return {"status": "started", "mode": system.mode}


@app.post("/api/stop")
async def stop_trading(_=Depends(require_admin_key)):
    system.status = "stopped"
    return {"status": "stopped", "position_management": "active"}


@app.post("/api/close-all", status_code=202)
async def close_all(_=Depends(require_admin_key)):
    system.status = "stopped"
    runtime.close_requested = True
    runtime.reconcile()
    for position in system.state.all_positions():
        position.exit_reason = "manual_close"
    save_state(system.state)
    runtime.manage_positions()
    return {"status": "close_requested", "remaining": len(system.state.all_positions()),
            "error": runtime.error}


@app.post("/api/cancel-all")
async def cancel_all(_=Depends(require_admin_key)):
    system.status = "stopped"
    try:
        for order in system.trader.open_orders():
            system.trader.trading_client.cancel_order_by_id(order['id'])
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Order cancellation failed") from exc
    return {"status": "cancellation_requested"}


def report_closed(position):
    exit_price = position.accounted_exit_value / position.accounted_exit_qty
    log_trade(symbol=position.symbol, side=position.side,
              entry_price=position.entry_price, exit_price=exit_price,
              shares=position.accounted_exit_qty, stop_price=position.stop_price,
              target_price=position.target_price, pnl=position.realized_pnl,
              exit_reason=position.exit_reason or "broker_exit", status="closed",
              notes=f"pos_id={position.position_id}")
    journal.close_entry(symbol=position.symbol, exit_price=exit_price,
                        exit_reason=position.exit_reason or "broker_exit",
                        trailing_stop_used=position.trailing_stop is not None,
                        breakeven_hit=position.breakeven_active)
    system.notifier.send_trade_alert({"symbol": position.symbol, "direction": "CLOSED",
                                     "entry": position.entry_price, "exit_price": exit_price,
                                     "pnl": position.realized_pnl})


def report_opened(position):
    log_trade(symbol=position.symbol, side=position.side,
              entry_price=position.entry_price, shares=position.shares,
              stop_price=position.stop_price, target_price=position.target_price,
              status="open", notes=f"pos_id={position.position_id}")
    journal.add_entry(symbol=position.symbol, side=position.side,
                      entry_price=position.entry_price, shares=position.shares,
                      stop_price=position.stop_price, target_price=position.target_price,
                      score=0, setup="InstitutionalStrategy; broker-confirmed fill",
                      regime="not recorded")


runtime = TradingRuntime(system, on_closed=report_closed, on_opened=report_opened)


async def sync_positions_on_startup():
    runtime.reconcile()


async def trading_loop():
    """One monitor task; stopping entries never stops protection of open exposure."""
    while True:
        try:
            if system.status == "running" or system.state.all_positions() or runtime.close_requested:
                runtime.tick(get_et_now(), allow_entries=system.status == "running",
                             skip_symbol=earnings_filter.should_skip)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Trading cycle failed")
        await asyncio.sleep(30)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
