"""
Configuration for the Institutional Footprint Strategy.
All parameters can be overridden via environment variables for runtime changes.
"""
import os
from dataclasses import dataclass, field
from datetime import time
from typing import Tuple


def _env_float(name: str, default: float) -> float:
    val = os.environ.get(name)
    return float(val) if val else default


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    return int(val) if val else default


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_time(name: str, default: str) -> time:
    val = os.environ.get(name, default)
    h, m = val.split(":")
    return time(int(h), int(m))


@dataclass
class StrategyConfig:
    # ─── Capital & Risk ───────────────────────────────────────────
    capital: float = _env_float("CAPITAL", 20_000)
    risk_per_trade: float = _env_float("RISK_PER_TRADE", 50)
    # Stops can slip through their trigger. Plan below the hard $50 ceiling so
    # ordinary execution noise does not turn a $50 plan into a $54 fill.
    execution_risk_buffer: float = max(0.5, min(_env_float("EXECUTION_RISK_BUFFER", 0.90), 1.0))
    rr_ratio: float = _env_float("RR_RATIO", 2.0)
    max_trades_per_day: int = min(_env_int("MAX_TRADES_PER_DAY", 2), 2)
    max_daily_loss: float = min(_env_float("MAX_DAILY_LOSS", 100), 100)
    target_daily_pnl: float = _env_float("TARGET_DAILY_PNL", 150)
    max_position_pct: float = _env_float("MAX_POSITION_PCT", 0.10)
    max_correlated_trades: int = _env_int("MAX_CORRELATED_TRADES", 2)
    
    # ─── Cooldown Management ─────────────────────────────────────
    cooldown_minutes_after_sl: int = _env_int("COOLDOWN_AFTER_SL", 45)
    cooldown_minutes_after_win: int = _env_int("COOLDOWN_AFTER_WIN", 10)
    max_consecutive_losses: int = min(_env_int("MAX_CONSECUTIVE_LOSSES", 2), 2)
    
    # ─── VWAP Parameters ─────────────────────────────────────────
    vwap_std_dev_multiplier: float = _env_float("VWAP_STD_DEV", 1.5)
    vwap_lookback_minutes: int = _env_int("VWAP_LOOKBACK_MIN", 390)
    
    # ─── Opening Range ───────────────────────────────────────────
    or_narrow_threshold: float = _env_float("OR_NARROW_THRESHOLD", 0.3)
    or_wide_threshold: float = _env_float("OR_WIDE_THRESHOLD", 1.0)
    
    # ─── Volume Filter ───────────────────────────────────────────
    volume_ma_length: int = _env_int("VOLUME_MA_LENGTH", 20)
    min_volume_mult: float = _env_float("MIN_VOLUME_MULT", 1.0)
    
    # ─── ATR Parameters ──────────────────────────────────────────
    atr_length: int = _env_int("ATR_LENGTH", 14)
    atr_stop_multiplier: float = _env_float("ATR_STOP_MULT", 1.5)
    trailing_stop_multiplier: float = _env_float("TRAILING_STOP_MULT", 2.0)
    trailing_stop_activation: float = _env_float("TRAILING_ACTIVATION", 1.0)
    
    # ─── Multi-Factor Scoring ────────────────────────────────────
    min_score_to_trade: int = _env_int("MIN_SCORE_TO_TRADE", 4)
    
    # ─── Market Regime Filter ────────────────────────────────────
    regime_filter: bool = _env_str("REGIME_FILTER", "true").lower() == "true"
    market_alignment_filter: bool = _env_str("MARKET_ALIGNMENT_FILTER", "true").lower() == "true"
    adx_trend_threshold: float = _env_float("ADX_TREND_THRESHOLD", 25.0)
    
    # ─── Max Drawdown Halt ───────────────────────────────────────
    max_drawdown_pct: float = _env_float("MAX_DRAWDOWN_PCT", 5.0)
    
    # ─── Profit Lock ─────────────────────────────────────────────
    profit_lock_enabled: bool = _env_str("PROFIT_LOCK", "true").lower() == "true"
    profit_lock_target: float = _env_float("PROFIT_LOCK_TARGET", 150.0)
    
    # ─── Trailing Stops ──────────────────────────────────────────
    trailing_stop_enabled: bool = _env_str("TRAILING_STOP", "true").lower() == "true"
    breakeven_activation: float = _env_float("BREAKEVEN_ACTIVATION", 1.0)

    max_sector_exposure: float = _env_float("MAX_SECTOR_EXPOSURE", 0.30)
    tech_symbols: Tuple[str, ...] = ('AAPL', 'MSFT', 'GOOGL', 'META', 'NVDA', 'AMD', 'TSLA')
    
    # ─── Timing (ET) ─────────────────────────────────────────────
    trading_start: time = _env_time("TRADING_START", "09:30")
    trading_end: time = _env_time("TRADING_END", "15:50")
    hard_close_time: time = _env_time("HARD_CLOSE_TIME", "15:50")
    morning_window_start: time = _env_time("MORNING_START", "09:45")
    morning_window_end: time = _env_time("MORNING_END", "11:00")
    afternoon_window_start: time = _env_time("AFTERNOON_START", "14:00")
    afternoon_window_end: time = _env_time("AFTERNOON_END", "15:30")
    
    # ─── Universe (override via env: UNIVERSE=AAPL,MSFT,GOOGL) ───
    _default_universe: Tuple[str, ...] = ('QQQ', 'AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'META')
    
    @property
    def universe(self) -> Tuple[str, ...]:
        val = os.environ.get("UNIVERSE")
        if val:
            liquid = set(self._default_universe)
            selected = tuple(v.strip().upper() for v in val.split(",")
                             if v.strip().upper() in liquid)
            return selected or self._default_universe
        return self._default_universe
    
    # ─── Backtest ────────────────────────────────────────────────
    backtest_days: int = _env_int("BACKTEST_DAYS", 90)
    commission: float = 0.0
    
    # ─── Discord ─────────────────────────────────────────────────
    discord_webhook_url: str = _env_str("DISCORD_WEBHOOK_URL", "")


config = StrategyConfig()
