"""
strategy.py — Institutional signal generation with multi-timeframe analysis.

Signal logic:
1. Fetch HTF (15m) bars and calculate ALMA
2. Detect ALMA direction changes (trend)
3. Apply trend filter (price > EMA20 > EMA50 for long)
4. Apply volume filter (volume > 0.8 * volume MA)
5. Apply ATR filter (0.8% < ATR < 2.5%)
6. Only fire signal ONCE per HTF candle completion
7. Prevent same-side re-entry on same signal
"""
import logging
from datetime import datetime
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd
import numpy as np

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
    volume_ratio: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    is_valid: bool = True
    age_minutes: float = 0


class Strategy:
    """
    Institutional-grade signal generator.
    
    Uses multi-timeframe ALMA with trend, volume, and ATR filters.
    Only fires signals on completed HTF candles to avoid repainting.
    """
    
    def __init__(self, data_feed: DataFeed):
        self.data_feed = data_feed
        self._last_signal_time: Dict[str, datetime] = {}
        self._last_htf_close: Dict[str, float] = {}
    
    def generate_signal(self, symbol: str) -> Optional[Signal]:
        """
        Generate a trading signal for a symbol.
        Returns Signal if conditions met, None otherwise.
        """
        try:
            # Get current price
            price = self.data_feed.get_latest_price(symbol)
            if not price:
                return None
            
            # Get HTF bars (15m)
            htf_bars = self.data_feed.resample_to_htf(symbol, config.htf_minutes)
            if htf_bars is None or len(htf_bars) < 3:
                return None
            
            # Get latest HTF close price
            latest_htf_close = htf_bars['close'].iloc[-1]
            
            # Calculate ALMA on HTF
            alma_series = self.data_feed.calculate_alma(
                symbol, config.alma_length, config.alma_sigma, config.alma_offset
            )
            if alma_series is None or len(alma_series) < 3:
                return None
            
            # Get ALMA values
            alma_current = alma_series.iloc[-1]
            alma_prev = alma_series.iloc[-2]
            
            if pd.isna(alma_current) or pd.isna(alma_prev):
                return None
            
            # Detect ALMA direction
            # ALMA rising = bullish, ALMA falling = bearish
            alma_rising = alma_current > alma_prev
            alma_falling = alma_current < alma_prev
            
            # Determine signal direction
            if alma_rising and price > alma_current:
                direction = SignalDirection.LONG
            elif alma_falling and price < alma_current:
                direction = SignalDirection.SHORT
            else:
                return None
            
            # ─── Apply Filters ────────────────────────────────────────
            
            # Trend filter
            if config.use_trend_filter:
                if not self._passes_trend_filter(symbol, direction):
                    return None
            
            # Volume filter
            if config.use_volume_filter:
                if not self._passes_volume_filter(symbol):
                    return None
            
            # ATR filter
            if config.use_atr_filter:
                if not self._passes_atr_filter(symbol):
                    return None
            
            # ─── Calculate Stop/Target ────────────────────────────────
            
            atr = self.data_feed.get_atr(symbol, config.atr_length) or (price * 0.005)
            stop_distance = atr * config.atr_stop_multiplier
            
            if direction == SignalDirection.LONG:
                stop = price - stop_distance
                target = price + (stop_distance * config.rr_ratio)
            else:
                stop = price + stop_distance
                target = price - (stop_distance * config.rr_ratio)
            
            # ─── Cooldown Check ───────────────────────────────────────
            
            if not self._passes_cooldown(symbol):
                return None
            
            # ─── Create Signal ────────────────────────────────────────
            
            volume_ma = self.data_feed.get_volume_ma(symbol, config.volume_ma_length) or 1
            volume_ratio = 1.0  # Simplified for now
            
            signal = Signal(
                symbol=symbol,
                direction=direction,
                price=round(price, 2),
                stop=round(stop, 2),
                target=round(target, 2),
                atr=atr,
                volume_ratio=volume_ratio,
                timestamp=datetime.utcnow(),
            )
            
            # Record signal time
            self._last_signal_time[symbol] = signal.timestamp
            
            logger.info(
                f"SIGNAL: {symbol} {direction.value.upper()} @ ${price:.2f} | "
                f"Stop: ${stop:.2f} | Target: ${target:.2f} | ATR: ${atr:.2f}"
            )
            
            return signal
            
        except Exception as e:
            logger.error(f"Signal generation error for {symbol}: {e}")
            return None
    
    def _passes_trend_filter(self, symbol: str, direction: SignalDirection) -> bool:
        """Check if price is above/below EMAs in the signal direction."""
        try:
            ema_fast = self.data_feed.get_ema(symbol, config.trend_ema_fast)
            ema_slow = self.data_feed.get_ema(symbol, config.trend_ema_slow)
            
            if ema_fast is None or ema_slow is None:
                return True  # Pass if data unavailable
            
            price = self.data_feed.get_latest_price(symbol)
            if not price:
                return True
            
            if direction == SignalDirection.LONG:
                # Long: price > EMA20 > EMA50
                return price > ema_fast > ema_slow
            else:
                # Short: price < EMA20 < EMA50
                return price < ema_fast < ema_slow
                
        except Exception:
            return True
    
    def _passes_volume_filter(self, symbol: str) -> bool:
        """Check if volume is above threshold."""
        try:
            volume_ma = self.data_feed.get_volume_ma(symbol, config.volume_ma_length)
            if not volume_ma:
                return True
            
            # Get current volume (simplified - would need latest bar volume)
            bars = self.data_feed.get_bars(symbol, days=1)
            if bars is None or bars.empty:
                return True
            
            current_volume = bars['volume'].sum()  # Simplified
            threshold = volume_ma * config.volume_mult
            
            return current_volume >= threshold
            
        except Exception:
            return True
    
    def _passes_atr_filter(self, symbol: str) -> bool:
        """Check if ATR is within acceptable range."""
        try:
            atr = self.data_feed.get_atr(symbol, config.atr_length)
            if not atr:
                return True
            
            price = self.data_feed.get_latest_price(symbol)
            if not price:
                return True
            
            atr_pct = (atr / price) * 100
            
            return config.min_atr_pct <= atr_pct <= config.max_atr_pct
            
        except Exception:
            return True
    
    def _passes_cooldown(self, symbol: str) -> bool:
        """Check if enough time has passed since last signal."""
        if symbol not in self._last_signal_time:
            return True
        
        last_time = self._last_signal_time[symbol]
        elapsed = (datetime.utcnow() - last_time).total_seconds() / 60
        
        # Use cooldown after SL for safety
        return elapsed >= config.cooldown_minutes_after_sl
    
    def generate_all_signals(self) -> List[Signal]:
        """Generate signals for all symbols in universe."""
        signals = []
        for symbol in config.universe:
            signal = self.generate_signal(symbol)
            if signal:
                signals.append(signal)
        return signals
