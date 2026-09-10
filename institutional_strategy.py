"""
institutional_strategy.py — Multi-factor institutional footprint strategy.

Alpha sources:
1. VWAP deviation mean reversion (institutional benchmark)
2. Opening range volatility compression (narrow OR = explosive moves)
3. Volume confirmation (institutional participation)
4. Time-of-day execution windows (when institutions are active)
5. Multi-factor scoring (only high-conviction trades)
"""
import logging
from datetime import datetime, time as dtime
from typing import Optional, List, Dict
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
    score: int
    vwap: float
    vwap_deviation: float
    or_range_pct: float
    volume_ratio: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


class InstitutionalStrategy:
    """
    Multi-factor institutional footprint strategy.
    
    Scores each setup on 5 factors. Only trades score >= 6/8.
    """
    
    def __init__(self, data_feed: DataFeed):
        self.data_feed = data_feed
    
    def calculate_vwap(self, symbol: str) -> Optional[float]:
        """Calculate VWAP (Volume-Weighted Average Price)."""
        try:
            bars = self.data_feed.get_bars_yfinance(symbol, days=1)
            if bars is None or bars.empty:
                return None
            
            typical_price = (bars['High'] + bars['Low'] + bars['Close']) / 3
            vwap = (typical_price * bars['Volume']).sum() / bars['Volume'].sum()
            return round(vwap, 2)
        except Exception as e:
            logger.error(f"VWAP calc failed for {symbol}: {e}")
            return None
    
    def calculate_vwap_bands(self, symbol: str, std_dev_multiplier: float = 1.5) -> Optional[Dict]:
        """Calculate VWAP standard deviation bands."""
        try:
            bars = self.data_feed.get_bars_yfinance(symbol, days=1)
            if bars is None or bars.empty:
                return None
            
            vwap = self.calculate_vwap(symbol)
            if not vwap:
                return None
            
            typical_price = (bars['High'] + bars['Low'] + bars['Close']) / 3
            variance = ((typical_price - vwap) ** 2 * bars['Volume']).sum() / bars['Volume'].sum()
            std_dev = np.sqrt(variance)
            
            return {
                'vwap': vwap,
                'upper': round(vwap + std_dev * std_dev_multiplier, 2),
                'lower': round(vwap - std_dev * std_dev_multiplier, 2),
                'std_dev': round(std_dev, 4),
            }
        except Exception as e:
            logger.error(f"VWAP bands failed for {symbol}: {e}")
            return None
    
    def calculate_opening_range(self, symbol: str) -> Optional[Dict]:
        """Calculate opening range (9:30-9:45 AM)."""
        try:
            bars = self.data_feed.get_bars_yfinance(symbol, days=1)
            if bars is None or bars.empty:
                return None
            
            # Filter to opening range (9:30-9:45 AM)
            or_bars = bars.between_time('09:30', '09:45')
            if or_bars.empty:
                return None
            
            or_high = or_bars['High'].max()
            or_low = or_bars['Low'].min()
            or_range = or_high - or_low
            or_range_pct = (or_high - or_low) / or_low * 100 if or_low > 0 else 0
            
            return {
                'high': or_high,
                'low': or_low,
                'range': or_range,
                'range_pct': or_range_pct,
                'is_narrow': or_range_pct < 0.3,
                'is_wide': or_range_pct > 1.0,
            }
        except Exception as e:
            logger.error(f"OR calc failed for {symbol}: {e}")
            return None
    
    def get_volume_ratio(self, symbol: str) -> Optional[float]:
        """Get current volume vs 20-period average."""
        try:
            bars = self.data_feed.get_bars_yfinance(symbol, days=5)
            if bars is None or bars.empty:
                return None
            
            current_volume = bars['Volume'].sum()
            volume_ma = bars['Volume'].rolling(window=20).mean().iloc[-1]
            
            if volume_ma == 0:
                return None
            
            return round(current_volume / volume_ma, 2)
        except Exception as e:
            logger.error(f"Volume ratio failed for {symbol}: {e}")
            return None
    
    def is_execution_window(self) -> bool:
        """Check if current time is in institutional execution window."""
        now = datetime.now().time()
        # Morning window: 9:45-11:00 AM
        morning = dtime(9, 45) <= now <= dtime(11, 0)
        # Afternoon window: 2:00-3:30 PM
        afternoon = dtime(14, 0) <= now <= dtime(15, 30)
        return morning or afternoon
    
    def generate_signal(self, symbol: str) -> Optional[Signal]:
        """
        Generate a signal using multi-factor scoring.
        
        Scoring (max 8 points):
        - VWAP deviation > 1.5 std dev: +2
        - Volume > 1.5x average: +2
        - Narrow opening range: +1
        - In execution window: +1
        - Price reverts through VWAP: +2
        
        Only trade if score >= 6.
        """
        try:
            price = self.data_feed.get_latest_price_yfinance(symbol)
            if not price:
                return None
            
            # Calculate all factors
            vwap_bands = self.calculate_vwap_bands(symbol)
            or_data = self.calculate_opening_range(symbol)
            volume_ratio = self.get_volume_ratio(symbol)
            
            if not all([vwap_bands, or_data, volume_ratio]):
                return None
            
            vwap = vwap_bands['vwap']
            upper_band = vwap_bands['upper']
            lower_band = vwap_bands['lower']
            
            # ─── Scoring ────────────────────────────────────────────
            score = 0
            direction = None
            
            # Factor 1: VWAP deviation (mean reversion)
            if price <= lower_band:
                score += 2
                direction = SignalDirection.LONG
            elif price >= upper_band:
                score += 2
                direction = SignalDirection.SHORT
            
            # Factor 2: Volume confirmation
            if volume_ratio >= 1.5:
                score += 2
            elif volume_ratio >= 1.0:
                score += 1
            
            # Factor 3: Narrow opening range
            if or_data['is_narrow']:
                score += 1
            
            # Factor 4: Execution window
            if self.is_execution_window():
                score += 1
            
            # Factor 5: Price reverts through VWAP (confirmation)
            if direction == SignalDirection.LONG and price > vwap:
                score += 2
            elif direction == SignalDirection.SHORT and price < vwap:
                score += 2
            
            # ─── Minimum Score Gate ─────────────────────────────────
            if score < 6:
                return None
            
            # ─── Calculate Stop/Target ──────────────────────────────
            atr = self.data_feed.get_atr(symbol, config.atr_length) or (price * 0.005)
            
            if direction == SignalDirection.LONG:
                stop = lower_band - (atr * 0.5)
                target = upper_band
            else:
                stop = upper_band + (atr * 0.5)
                target = lower_band
            
            return Signal(
                symbol=symbol,
                direction=direction,
                price=round(price, 2),
                stop=round(stop, 2),
                target=round(target, 2),
                score=score,
                vwap=vwap,
                vwap_deviation=round((price - vwap) / vwap_bands['std_dev'], 2) if vwap_bands['std_dev'] > 0 else 0,
                or_range_pct=round(or_data['range_pct'], 3),
                volume_ratio=volume_ratio,
            )
            
        except Exception as e:
            logger.error(f"Signal generation error for {symbol}: {e}")
            return None
    
    def generate_all_signals(self) -> List[Signal]:
        """Generate signals for all symbols in universe."""
        signals = []
        for symbol in config.universe:
            signal = self.generate_signal(symbol)
            if signal:
                signals.append(signal)
        
        # Sort by score (highest conviction first)
        signals.sort(key=lambda x: x.score, reverse=True)
        return signals
