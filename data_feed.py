"""
data_feed.py — Market data fetching using yfinance.
Alpaca free tier has SIP data limits, so we use yfinance for market data.
Alpaca is used only for trading execution.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List

import pandas as pd
import numpy as np
import yfinance as yf

from alpaca_trader import AlpacaTrader
from config import config

logger = logging.getLogger(__name__)


class DataFeed:
    """Fetch and process market data using yfinance."""
    
    def __init__(self, trader: AlpacaTrader):
        self.trader = trader
    
    def get_bars_yfinance(self, symbol: str, days: int = 5) -> Optional[pd.DataFrame]:
        """Fetch recent price bars using yfinance."""
        try:
            end = datetime.now()
            start = end - timedelta(days=days + 3)
            
            ticker = yf.Ticker(symbol)
            df = ticker.history(
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval="1m",
                prepost=True,
                repair=True,
            )
            
            if df.empty:
                return None
            
            # Normalize index
            df.index = df.index.tz_localize(None) if df.index.tz else df.index
            df = df.sort_index()
            
            return df
        except Exception as e:
            logger.error(f"Failed to get bars for {symbol}: {e}")
            return None
    
    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Get latest price using yfinance."""
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period="1d", interval="1m")
            if not data.empty:
                return round(float(data['Close'].iloc[-1]), 2)
            return None
        except Exception as e:
            logger.error(f"Failed to get price for {symbol}: {e}")
            return None
    
    def get_atr(self, symbol: str, period: int = 14) -> Optional[float]:
        """Calculate Average True Range."""
        try:
            bars = self.get_bars_yfinance(symbol, days=5)
            if bars is None or len(bars) < period:
                return None
            
            high = bars['High']
            low = bars['Low']
            prev_close = bars['Close'].shift(1)
            
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
    
    def get_adx(self, symbol: str, period: int = 14) -> Optional[float]:
        """Calculate Average Directional Index for trend strength."""
        try:
            bars = self.get_bars_yfinance(symbol, days=5)
            if bars is None or len(bars) < period + 1:
                return None
            
            high = bars['High']
            low = bars['Low']
            close = bars['Close']
            
            plus_dm = high.diff()
            minus_dm = -low.diff()
            
            plus_dm[plus_dm < 0] = 0
            minus_dm[minus_dm < 0] = 0
            
            tr = pd.concat([
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs()
            ], axis=1).max(axis=1)
            
            atr = tr.rolling(window=period).mean()
            plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
            minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
            
            dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
            adx = dx.rolling(window=period).mean().iloc[-1]
            
            return round(adx, 2) if not np.isnan(adx) else None
        except Exception as e:
            logger.error(f"Failed to get ADX for {symbol}: {e}")
            return None
    
    def get_volume_ma(self, symbol: str, period: int = 20) -> Optional[float]:
        """Calculate Volume Moving Average."""
        try:
            bars = self.get_bars_yfinance(symbol, days=5)
            if bars is None or len(bars) < period:
                return None
            
            volume_ma = bars['Volume'].rolling(window=period).mean().iloc[-1]
            return float(volume_ma)
        except Exception as e:
            logger.error(f"Failed to get volume MA for {symbol}: {e}")
            return None
    
    def get_ema(self, symbol: str, period: int = 20) -> Optional[float]:
        """Calculate Exponential Moving Average."""
        try:
            bars = self.get_bars_yfinance(symbol, days=10)
            if bars is None or len(bars) < period:
                return None
            
            ema = bars['Close'].ewm(span=period, adjust=False).mean().iloc[-1]
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
    
    def calculate_vwap(self, symbol: str) -> Optional[float]:
        """Calculate VWAP (Volume-Weighted Average Price)."""
        try:
            bars = self.get_bars_yfinance(symbol, days=1)
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
            bars = self.get_bars_yfinance(symbol, days=1)
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
            bars = self.get_bars_yfinance(symbol, days=1)
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
                'is_narrow': or_range_pct < config.or_narrow_threshold,
                'is_wide': or_range_pct > config.or_wide_threshold,
            }
        except Exception as e:
            logger.error(f"OR calc failed for {symbol}: {e}")
            return None
    
    def get_volume_ratio(self, symbol: str) -> Optional[float]:
        """Get current volume vs 20-period average."""
        try:
            bars = self.get_bars_yfinance(symbol, days=5)
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
    
    def get_historical_bars(self, symbol: str, days: int = 30) -> Optional[pd.DataFrame]:
        """Get historical daily bars for volatility calculations."""
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=f"{days}d", interval="1d")
            if df.empty:
                return None
            return df
        except Exception as e:
            logger.error(f"Failed to get historical bars for {symbol}: {e}")
            return None
