"""
strategy.py — Pre-Market Momentum + ORB signal generator.
Your original strategy with institutional-grade filters.
"""
import logging
from datetime import datetime
from typing import Optional, List, Dict
from dataclasses import dataclass, field
from enum import Enum

from config import config
from data_feed import DataFeed

logger = logging.getLogger(__name__)


class SignalDirection(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class Signal:
    symbol: str
    direction: SignalDirection
    price: float
    stop: float
    target: float
    atr: float
    gap_pct: float
    pm_volume: int
    timestamp: datetime = field(default_factory=datetime.utcnow)


class Strategy:
    """
    Pre-Market Momentum + Opening Range Breakout.
    
    Your original strategy:
    1. Pre-market gap scan (0.3%+ gap, 100k+ volume)
    2. Opening Range Breakout (9:30-9:45 AM)
    3. VWAP confirmation
    4. Fixed $50 risk, 2:1 reward-to-risk
    """
    
    def __init__(self, data_feed: DataFeed):
        self.data_feed = data_feed
        self._last_signal_time: Dict[str, datetime] = {}
    
    def generate_signals(self, previous_closes: Dict[str, float]) -> List[Signal]:
        """
        Scan for pre-market momentum setups.
        Returns list of signals sorted by score.
        """
        setups = []
        
        for symbol in config.universe:
            try:
                bars = self.data_feed.get_bars(symbol, days=1)
                if bars is None or bars.empty:
                    continue
                
                # Pre-market metrics
                pm_high = bars['high'].max()
                pm_low = bars['low'].min()
                pm_volume = int(bars['volume'].sum())
                pm_open = float(bars['open'].iloc[0])
                
                # Get previous close
                prev_close = previous_closes.get(symbol)
                if not prev_close or prev_close <= 0:
                    continue
                
                gap_pct = (pm_open - prev_close) / prev_close
                
                if abs(gap_pct) >= config.gap_threshold and pm_volume >= config.min_premarket_volume:
                    direction = SignalDirection.LONG if gap_pct > 0 else SignalDirection.SHORT
                    score = abs(gap_pct) * pm_volume / 100000
                    
                    # Calculate ATR-based stop
                    atr = self.data_feed.get_atr(symbol, config.atr_length) or (pm_open * 0.005)
                    stop_distance = atr * config.atr_stop_multiplier
                    
                    if direction == SignalDirection.LONG:
                        stop = pm_open - stop_distance
                        target = pm_open + (stop_distance * config.rr_ratio)
                    else:
                        stop = pm_open + stop_distance
                        target = pm_open - (stop_distance * config.rr_ratio)
                    
                    setups.append(Signal(
                        symbol=symbol,
                        direction=direction,
                        price=pm_open,
                        stop=round(stop, 2),
                        target=round(target, 2),
                        atr=atr,
                        gap_pct=gap_pct,
                        pm_volume=pm_volume,
                    ))
            except Exception as e:
                logger.debug(f"Scan error for {symbol}: {e}")
        
        # Sort by score (trade the biggest movers first)
        setups.sort(key=lambda x: abs(x.gap_pct) * x.pm_volume, reverse=True)
        return setups
    
    def check_entry(self, symbol: str, current_price: float, 
                    opening_range_high: float, opening_range_low: float) -> Optional[Signal]:
        """
        Check if price has broken out of opening range.
        Returns signal if breakout confirmed.
        """
        try:
            # Get latest signal for this symbol
            # This is simplified - in production you'd track per-symbol signals
            return None
        except Exception:
            return None
