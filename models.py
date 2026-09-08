"""
Pydantic models for the trading API.
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict
from pydantic import BaseModel


class TradingStatus(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAPER = "paper"
    LIVE = "live"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class FillStatus(str, Enum):
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    PENDING = "pending"


class TradeSignal(BaseModel):
    symbol: str
    side: OrderSide
    entry: float
    stop: float
    target: float
    size: int
    gap_pct: float
    direction: str
    timestamp: datetime = datetime.utcnow()


class FillResult(BaseModel):
    symbol: str
    side: OrderSide
    requested_price: float
    fill_price: float
    size: int
    slippage: float
    commission: float
    status: FillStatus
    reason: Optional[str] = None
    timestamp: datetime = datetime.utcnow()


class Position(BaseModel):
    symbol: str
    side: str
    entry: float
    current_price: float
    size: int
    stop: float
    target: float
    pnl: float
    pnl_pct: float
    entry_time: datetime


class TradeRecord(BaseModel):
    symbol: str
    side: str
    entry: float
    exit_price: float
    size: float
    pnl: float
    entry_time: datetime
    exit_time: datetime
    exit_reason: str


class DailyStats(BaseModel):
    date: str
    trades: int
    wins: int
    losses: int
    win_rate: float
    pnl: float
    portfolio: float


class SystemStatus(BaseModel):
    status: TradingStatus
    mode: str
    uptime: float
    daily_pnl: float
    total_trades: int
    active_positions: int
    portfolio_value: float
    buying_power: float


class BacktestRequest(BaseModel):
    symbol: str
    days: int = 180


class ScanResult(BaseModel):
    symbol: str
    direction: str
    gap_pct: float
    pm_volume: int
    pm_high: float
    pm_low: float
    score: float
