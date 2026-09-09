"""
Configuration for the Pre-Market Momentum + ORB strategy.
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

    # ─── Entry Criteria ──────────────────────────────────────────
    gap_threshold: float = 0.003        # 0.3% gap (realistic for liquid stocks)
    min_premarket_volume: int = 100_000
    rr_ratio: float = 2.0               # 2:1 for $100 winners (was 1.5)

    # ─── Timing ──────────────────────────────────────────────────
    trading_start: time = time(9, 30)
    trading_end: time = time(15, 50)  # 3:50 PM — 10 mins before market close
    or_start: time = time(9, 30)       # Opening range start
    or_end: time = time(9, 45)         # Opening range end

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
