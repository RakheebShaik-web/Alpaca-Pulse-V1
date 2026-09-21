"""Shared planned-risk policy for live execution and historical replay."""
from decimal import Decimal, ROUND_FLOOR
from math import isfinite
from datetime import datetime

from config import config


def position_size(entry: float, stop: float, equity: float, buying_power: float) -> int:
    """Whole shares sized only by the fixed risk budget and available buying power."""
    values = (entry, stop, equity, buying_power, config.risk_per_trade)
    if not all(isfinite(v) and v > 0 for v in values) or entry == stop:
        return 0
    price = Decimal(str(entry))
    distance = abs(price - Decimal(str(stop)))
    hard_cap = min(Decimal('50'), Decimal(str(config.risk_per_trade)))
    risk_qty = hard_cap * Decimal(str(config.execution_risk_buffer)) / distance
    value_cap = Decimal(str(buying_power))
    return int(min(risk_qty, value_cap / price).to_integral_value(rounding=ROUND_FLOOR))


def reset_session(state, now) -> bool:
    session = now.date().isoformat()
    if state.session_date == session:
        return False
    state.session_date = session
    state.daily_pnl = 0.0
    state.trades_today = 0
    state.consecutive_losses = 0
    state.last_trade_at = None
    state.last_sl_at = None
    return True


def entries_allowed(state, strategy, equity: float) -> bool:
    now = strategy.clock()
    last_loss = datetime.fromisoformat(state.last_sl_at.replace('Z', '+00:00')) if state.last_sl_at else None
    if last_loss is not None:
        if now.tzinfo is None and last_loss.tzinfo is not None:
            last_loss = last_loss.replace(tzinfo=None)
        elif now.tzinfo is not None and last_loss.tzinfo is None:
            last_loss = last_loss.replace(tzinfo=now.tzinfo)
        if (now - last_loss).total_seconds() < config.cooldown_minutes_after_sl * 60:
            return False
    return (equity > 0 and strategy.is_execution_window()
            and state.trades_today < config.max_trades_per_day
            and state.daily_pnl > -config.max_daily_loss
            and state.consecutive_losses < config.max_consecutive_losses
            and not strategy.check_max_drawdown(equity))
