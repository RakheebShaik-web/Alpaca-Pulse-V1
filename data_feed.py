"""
data_feed.py — Multi-timeframe market data fetching.
Institutional-grade with proper error handling and data validation.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple

import pandas as pd
import numpy as np

from alpaca_trader import AlpacaTrader
from config import config

logger = logging.getLogger(__name__)


class DataFeed:
    """Fetch and process multi-timeframe market data."""
    
    def __init__(self, trader: AlpacaTrader):
        self.trader = trader
    
    def get_bars(self, symbol: str, days: int = 5) -> Optional[pd.DataFrame]:
        """Fetch recent price bars."""
        try:
            return self.trader.get_bars(symbol, days)
        except Exception as e:
            logger.error(f"Failed to get bars for {symbol}: {e}")
            return None
    
    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Get latest mid-price."""
        try:
            return self.trader.get_latest_price(symbol)
        except Exception as e:
            logger.error(f"Failed to get price for {symbol}: {e}")
            return None
    
    def get_atr(self, symbol: str, period: int = 14) -> Optional[float]:
        """Calculate Average True Range."""
        try:
            bars = self.get_bars(symbol, days=5)
            if bars is None or len(bars) < period:
                return None
            
            high = bars['high']
            low = bars['low']
            prev_close = bars['close'].shift(1)
            
            tr = pd.concat([
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs()
            ], axis=1).max(axis=1)
            
            atr = tr.rolling(window=period).mean().iloc[-1]
            return round(atr, 2)
        except Exception as e:
            logger.error(f"Failed to get ATR for {symbol}: {e}")
            return None
    
    def get_volume_ma(self, symbol: str, period: int = 20) -> Optional[float]:
        """Calculate Volume Moving Average."""
        try:
            bars = self.get_bars(symbol, days=5)
            if bars is None or len(bars) < period:
                return None
            
            volume_ma = bars['volume'].rolling(window=period).mean().iloc[-1]
            return int(volume_ma)
        except Exception as e:
            logger.error(f"Failed to get volume MA for {symbol}: {e}")
            return None
    
    def get_ema(self, symbol: str, period: int = 20) -> Optional[float]:
        """Calculate Exponential Moving Average."""
        try:
            bars = self.get_bars(symbol, days=10)
            if bars is None or len(bars) < period:
                return None
            
            ema = bars['close'].ewm(span=period, adjust=False).mean().iloc[-1]
            return round(ema, 2)
        except Exception as e:
            logger.error(f"Failed to get EMA for {symbol}: {e}")
            return None
    
    def is_market_open(self) -> bool:
        """Check if the market is currently open."""
        try:
            return self.trader.is_market_open()
        except Exception as e:
            logger.error(f"Market check failed: {e}")
            return False
    
    def get_clock(self) -> Optional[dict]:
        """Get market clock."""
        try:
            return self.trader.get_clock()
        except Exception as e:
            logger.error(f"Clock fetch failed: {e}")
            return None
    
    def calculate_alma(self, symbol: str, length: int = 2, sigma: float = 5.0, offset: float = 0.85) -> Optional[pd.Series]:
        """
        Calculate ALMA (Arnaud Legoux Moving Average).
        Institutional-grade smoothing with Gaussian distribution.
        """
        try:
            bars = self.get_bars(symbol, days=10)
            if bars is None or len(bars) < length:
                return None
            
            close = bars['close'].values
            alma = self._alma(close, length, sigma, offset)
            return pd.Series(alma, index=bars.index)
        except Exception as e:
            logger.error(f"Failed to calculate ALMA for {symbol}: {e}")
            return None
    
    def _alma(self, data: np.ndarray, length: int, sigma: float, offset: float) -> np.ndarray:
        """ALMA calculation with Gaussian weights."""
        m = offset * (length - 1)
        s = length / sigma
        w = np.exp(-((np.arange(length) - m) ** 2) / (2 * s ** 2))
        w = w / w.sum()
        
        alma = np.convolve(data, w[::-1], mode='valid')
        # Pad with NaN for alignment
        pad = len(data) - len(alma)
        return np.concatenate([np.full(pad, np.nan), alma])
    
    def resample_to_htf(self, symbol: str, htf_minutes: int = 15) -> Optional[pd.DataFrame]:
        """
        Resample 5m bars to higher timeframe (15m, 2h, etc.).
        Used for multi-timeframe analysis.
        """
        try:
            bars = self.get_bars(symbol, days=5)
            if bars is None or bars.empty:
                return None
            
            # Resample to HTF
            rule = f'{htf_minutes}min'
            htf_bars = bars.resample(rule).agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            
            return htf_bars
        except Exception as e:
            logger.error(f"Failed to resample {symbol} to {htf_minutes}m: {e}")
            return None
    
    def get_highest_high(self, symbol: str, lookback: int = 20) -> Optional[float]:
        """Get highest high over lookback period."""
        try:
            bars = self.get_bars(symbol, days=5)
            if bars is None or len(bars) < lookback:
                return None
            
            return bars['high'].rolling(window=lookback).max().iloc[-1]
        except Exception as e:
            logger.error(f"Failed to get highest high for {symbol}: {e}")
            return None
    
    def get_lowest_low(self, symbol: str, lookback: int = 20) -> Optional[float]:
        """Get lowest low over lookback period."""
        try:
            bars = self.get_bars(symbol, days=5)
            if bars is None or len(bars) < lookback:
                return None
            
            return bars['low'].rolling(window=lookback).min().iloc[-1]
        except Exception as e:
            logger.error(f"Failed to get lowest low for {symbol}: {e}")
            return None
