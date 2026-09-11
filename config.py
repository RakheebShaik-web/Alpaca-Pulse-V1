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
    rr_ratio: float = 2.0
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
    vwap_lookback_minutes: int = 390
    
    # ─── Opening Range ───────────────────────────────────────────
    or_narrow_threshold: float = 0.3
    or_wide_threshold: float = 1.0
    
    # ─── Volume Filter ───────────────────────────────────────────
    volume_ma_length: int = 20
    min_volume_mult: float = 1.0
    
    # ─── ATR Parameters ──────────────────────────────────────────
    atr_length: int = 14
    atr_stop_multiplier: float = 1.5
    trailing_stop_multiplier: float = 2.0  # Trailing stop distance
    trailing_stop_activation: float = 1.0  # Activate after 1R profit
    
    # ─── Multi-Factor Scoring ────────────────────────────────────
    min_score_to_trade: int = 4
    
    # ─── Volatility Targeting ────────────────────────────────────
    target_volatility: float = 0.15  # 15% annualized vol target
    vol_lookback_days: int = 20
    
    # ─── Market Regime Filter ────────────────────────────────────
    regime_filter: bool = True
    adx_trend_threshold: float = 25.0  # ADX > 25 = trending
    
    # ─── Max Drawdown Halt ───────────────────────────────────────
    max_drawdown_pct: float = 5.0  # Halt if account drops 5%
    
    # ─── Profit Lock ─────────────────────────────────────────────
    profit_lock_enabled: bool = True
    profit_lock_target: float = 150.0  # Lock profits at $150
    
    # ─── Trailing Stops ──────────────────────────────────────────
    trailing_stop_enabled: bool = True
    breakeven_activation: float = 1.0  # Move to BE after 1R
    
    # ─── Sector Exposure ─────────────────────────────────────────
    max_sector_exposure: float = 0.30  # Max 30% in one sector
    tech_symbols: Tuple[str, ...] = ('AAPL', 'MSFT', 'GOOGL', 'META', 'NVDA', 'AMD', 'TSLA')
    
    # ─── Timing ──────────────────────────────────────────────────
    trading_start: time = time(9, 30)
    trading_end: time = time(15, 50)
    morning_window_start: time = time(9, 45)
    morning_window_end: time = time(11, 0)
    afternoon_window_start: time = time(14, 0)
    afternoon_window_end: time = time(15, 30)
    
    # ─── Universe (top 20 liquid, no PLTR, no banks, no META, no defense) ───
    universe: Tuple[str, ...] = (
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA',
        'TSLA', 'AMD', 'SPY', 'QQQ', 'JNJ',
        'WMT', 'PG', 'HD', 'DIS', 'NFLX',
        'INTC', 'CRM', 'ORCL', 'CSCO', 'RKLB',
        'ASTS',
    )
    
    # ─── Backtest ────────────────────────────────────────────────
    backtest_days: int = 90
    commission: float = 0.0
    
    # ─── Discord ─────────────────────────────────────────────────
    discord_webhook_url: str = ""


config = StrategyConfig()
