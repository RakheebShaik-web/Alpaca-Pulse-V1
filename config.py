"""
Configuration for the Pre-Market Momentum + ORB strategy.
Institutional-grade parameters with multi-timeframe analysis.
"""
from dataclasses import dataclass, field
from datetime import time
from typing import Tuple


@dataclass
class StrategyConfig:
    # ─── Capital & Risk ───────────────────────────────────────────
    # Cash account: no PDT, but T+2 settlement means we can't reuse
    # sale proceeds for 2 days. Size positions accordingly.
    capital: float = 20_000
    risk_per_trade: float = 50
    max_trades_per_day: int = 3
    max_daily_loss: float = 200
    target_daily_pnl: float = 150
    max_position_pct: float = 0.10        # Max 10% of capital per position
    max_correlated_trades: int = 2        # Max 2 tech/correlated names
    use_atr_sizing: bool = True          # Use ATR for position sizing
    
    # ─── Cooldown Management ─────────────────────────────────────
    cooldown_minutes_after_sl: int = 45   # Wait 45 min after stop loss
    cooldown_minutes_after_win: int = 10  # Wait 10 min after win
    max_consecutive_losses: int = 3       # Stop after 3 consecutive losses
    
    # ─── Entry Criteria ──────────────────────────────────────────
    gap_threshold: float = 0.003        # 0.3% gap (realistic for liquid stocks)
    min_premarket_volume: int = 100_000
    rr_ratio: float = 2.0               # 2:1 for $100 winners (was 1.5)
    
    # ─── Multi-Timeframe Signal Parameters ───────────────────────
    # ALMA (Arnaud Legoux Moving Average) on HTF
    alma_length: int = 2
    alma_sigma: float = 5.0
    alma_offset: float = 0.85
    base_minutes: int = 5               # Base timeframe (5m)
    htf_minutes: int = 15               # Higher timeframe (15m)
    signal_window_candles: int = 2       # Keep HTF signal valid briefly
    max_candle_age_minutes: int = 15     # Never trade stale data
    max_signal_age_minutes: int = 12     # Never execute old signal
    
    # ─── Trend Filter ────────────────────────────────────────────
    use_trend_filter: bool = True
    trend_ema_fast: int = 20
    trend_ema_slow: int = 50
    
    # ─── Volume Filter ───────────────────────────────────────────
    use_volume_filter: bool = True
    volume_ma_length: int = 20
    volume_mult: float = 0.8            # Volume must be > 80% of MA
    
    # ─── ATR Filter ──────────────────────────────────────────────
    use_atr_filter: bool = True
    atr_length: int = 14
    min_atr_pct: float = 0.08           # Min 0.8% ATR (avoid low vol)
    max_atr_pct: float = 2.5            # Max 2.5% ATR (avoid extreme vol)
    atr_stop_multiplier: float = 1.5    # Stop = 1.5x ATR
    
    # ─── Take Profit Levels ──────────────────────────────────────
    tp1_rr: float = 0.8                 # TP1 = 0.8 x SL distance
    tp2_rr: float = 1.0                 # TP2 = 1.0 x SL distance
    tp3_rr: float = 1.5                 # TP3 = 1.5 x SL distance
    tp1_qty_pct: float = 34.0           # Exit 34% at TP1
    tp2_qty_pct: float = 50.0           # Exit 50% of remaining at TP2
    tp3_qty_pct: float = 100.0          # Exit remainder at TP3
    
    # ─── Timing ──────────────────────────────────────────────────
    trading_start: time = time(9, 30)
    trading_end: time = time(15, 50)    # 3:50 PM — 10 mins before market close
    or_start: time = time(9, 30)        # Opening range start
    or_end: time = time(9, 45)          # Opening range end
    
    # ─── Universe (top liquid names, NVDA removed - negative PF) ──
    universe: Tuple[str, ...] = (
        'AMZN', 'SPY', 'AAPL', 'GOOGL', 'AMD',
        'QQQ', 'META', 'TSLA', 'MSFT',
    )
    
    # ─── Backtest ────────────────────────────────────────────────
    backtest_days: int = 90
    commission: float = 0.0            # Alpaca is commission-free
    
    # ─── Discord ─────────────────────────────────────────────────
    discord_webhook_url: str = ""      # Set in .env


config = StrategyConfig()
