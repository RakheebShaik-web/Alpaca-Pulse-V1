"""Shared planned-risk policy for live execution and historical replay."""
from decimal import Decimal, ROUND_FLOOR
from math import isfinite

from config import config


def position_size(entry: float, stop: float, equity: float, buying_power: float) -> int:
    """Whole shares, rounded down: planned stop risk never exceeds $50."""
    values = (entry, stop, equity, buying_power, config.risk_per_trade)
    if not all(isfinite(v) and v > 0 for v in values) or entry == stop:
        return 0
    price = Decimal(str(entry))
    distance = abs(price - Decimal(str(stop)))
    risk_qty = Decimal(str(config.risk_per_trade)) / distance
    value_cap = min(Decimal(str(equity)) * Decimal(str(config.max_position_pct)),
                    Decimal(str(buying_power)))
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
    return (equity > 0 and strategy.is_execution_window()
            and state.trades_today < config.max_trades_per_day
            and state.daily_pnl > -config.max_daily_loss
            and state.consecutive_losses < config.max_consecutive_losses
            and not strategy.check_max_drawdown(equity))
