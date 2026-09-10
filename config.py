"""
Configuration for the Institutional Footprint Strategy.
"""
from dataclasses import dataclass, field
from datetime import time
from typing import Tuple


@dataclass
class StrategyConfig:
    # ─── Capital & Risk ───────────────────────────────────────────
    capital: float = 20_000
    risk_per_trade: float = 50
    max_trades_per_day: int = 3
    max_daily_loss: float = 200
    target_daily_pnl: float = 150
    max_position_pct: float = 0.10
    max_correlated_trades: int = 2
    
    # ─── Cooldown Management ─────────────────────────────────────
    cooldown_minutes_after_sl: int = 45
    cooldown_minutes_after_win: int = 10
    max_consecutive_losses: int = 3
    
    # ─── VWAP Parameters ─────────────────────────────────────────
    vwap_std_dev_multiplier: float = 1.5
    vwap_lookback_minutes: int = 390  # Full trading day
    
    # ─── Opening Range ───────────────────────────────────────────
    or_narrow_threshold: float = 0.3   # < 0.3% = narrow (high edge)
    or_wide_threshold: float = 1.0     # > 1.0% = wide (no trade)
    
    # ─── Volume Filter ───────────────────────────────────────────
    volume_ma_length: int = 20
    min_volume_mult: float = 1.5       # Volume must be > 1.5x average
    
    # ─── ATR Parameters ──────────────────────────────────────────
    atr_length: int = 14
    atr_stop_multiplier: float = 1.5
    
    # ─── Multi-Factor Scoring ────────────────────────────────────
    min_score_to_trade: int = 4        # Out of 8 max (lowered from 6 for more trades)
    
    # ─── Timing ──────────────────────────────────────────────────
    trading_start: time = time(9, 30)
    trading_end: time = time(15, 50)
    morning_window_start: time = time(9, 45)
    morning_window_end: time = time(11, 0)
    afternoon_window_start: time = time(14, 0)
    afternoon_window_end: time = time(15, 30)
    
    # ─── Universe ────────────────────────────────────────────────
    universe: Tuple[str, ...] = (
        'AMZN', 'SPY', 'AAPL', 'GOOGL', 'AMD',
        'QQQ', 'META', 'TSLA', 'MSFT',
    )
    
    # ─── Backtest ────────────────────────────────────────────────
    backtest_days: int = 90
    commission: float = 0.0
    
    # ─── Discord ─────────────────────────────────────────────────
    discord_webhook_url: str = ""


config = StrategyConfig()
