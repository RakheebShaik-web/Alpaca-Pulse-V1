"""
institutional_strategy.py — Multi-factor institutional footprint strategy.

Alpha sources:
1. VWAP deviation mean reversion (institutional benchmark)
2. Opening range volatility compression (narrow OR = explosive moves)
3. Volume confirmation (institutional participation)
4. Time-of-day execution windows (when institutions are active)
5. Multi-factor scoring (only high-conviction trades)
6. ADX trend filter (avoid choppy markets)
7. Trailing stops (lock in profits)
8. Breakeven activation (protect capital)
"""
import logging
from datetime import datetime, time as dtime
from typing import Optional, List, Dict
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd
import numpy as np
import pytz

from config import config
from data_feed import DataFeed

logger = logging.getLogger(__name__)

# US Eastern timezone for market hours
ET = pytz.timezone('US/Eastern')


def get_et_now() -> datetime:
    """Get current time in US Eastern timezone."""
    return datetime.now(ET)


def get_et_time() -> dtime:
    """Get current time in US Eastern timezone."""
    return get_et_now().time()


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
    adx: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Position:
    symbol: str
    direction: SignalDirection
    entry_price: float
    shares: float
    stop: float
    target: float
    entry_time: datetime = field(default_factory=datetime.utcnow)
    highest_profit: float = 0.0
    trailing_stop: Optional[float] = None
    breakeven_active: bool = False
    initial_risk: float = 0.0
    
    def __post_init__(self):
        self.initial_risk = abs(self.entry_price - self.stop)

    def update_trailing_stop(self, current_price: float, atr: float):
        """Update trailing stop based on highest profit."""
        if not config.trailing_stop_enabled:
            return
        if self.direction == SignalDirection.LONG:
            profit = current_price - self.entry_price
            if profit > self.highest_profit:
                self.highest_profit = profit
            # Activate breakeven after 1R profit
            if profit >= self.initial_risk * config.breakeven_activation and not self.breakeven_active:
                self.breakeven_active = True
                self.trailing_stop = self.entry_price
            # Trailing stop: 2x ATR from highest point
            if self.highest_profit >= self.initial_risk * config.trailing_stop_activation:
                trail_distance = atr * config.trailing_stop_multiplier
                new_trail = current_price - trail_distance
                if self.trailing_stop is None or new_trail > self.trailing_stop:
                    self.trailing_stop = new_trail
        else:
            profit = self.entry_price - current_price
            if profit > self.highest_profit:
                self.highest_profit = profit
            if profit >= self.initial_risk * config.breakeven_activation and not self.breakeven_active:
                self.breakeven_active = True
                self.trailing_stop = self.entry_price
            if self.highest_profit >= self.initial_risk * config.trailing_stop_activation:
                trail_distance = atr * config.trailing_stop_multiplier
                new_trail = current_price + trail_distance
                if self.trailing_stop is None or new_trail < self.trailing_stop:
                    self.trailing_stop = new_trail
    
    def should_exit(self, current_price: float) -> tuple[bool, str]:
        """Check if position should be exited."""
        if self.direction == SignalDirection.LONG:
            if current_price <= self.stop:
                return True, "stop_loss"
            if current_price >= self.target:
                return True, "target"
            if self.trailing_stop and current_price <= self.trailing_stop and self.breakeven_active:
                return True, "trailing_stop"
        else:
            if current_price >= self.stop:
                return True, "stop_loss"
            if current_price <= self.target:
                return True, "target"
            if self.trailing_stop and current_price >= self.trailing_stop and self.breakeven_active:
                return True, "trailing_stop"
        return False, ""


class InstitutionalStrategy:
    """
    Multi-factor institutional footprint strategy.
    """
    
    def __init__(self, data_feed: DataFeed, clock=get_et_now):
        self.data_feed = data_feed
        self.clock = clock
        self.positions: Dict[str, Position] = {}
        self.portfolio_peak: float = 20000.0
        self.daily_peak: float = 0.0
    
    def calculate_vwap(self, symbol: str) -> Optional[float]:
        """Calculate VWAP."""
        try:
            bars = self.data_feed.get_bars_yfinance(symbol, days=1)
            if bars is None or bars.empty:
                return None
            bars = bars.loc[bars.index.date == self.clock().date()]
            if bars.empty:
                return None
            typical_price = (bars['High'] + bars['Low'] + bars['Close']) / 3
            vwap = (typical_price * bars['Volume']).sum() / bars['Volume'].sum()
            return round(vwap, 2)
        except Exception as e:
            logger.error(f"VWAP calc failed for {symbol}: {e}")
            return None
    
    def calculate_vwap_bands(self, symbol: str) -> Optional[Dict]:
        """Calculate VWAP standard deviation bands."""
        try:
            bars = self.data_feed.get_bars_yfinance(symbol, days=1)
            if bars is None or bars.empty:
                return None
            
            vwap = self.calculate_vwap(symbol)
            if not vwap:
                return None
            
            bars = bars.loc[bars.index.date == self.clock().date()]
            if bars.empty:
                return None
            typical_price = (bars['High'] + bars['Low'] + bars['Close']) / 3
            variance = ((typical_price - vwap) ** 2 * bars['Volume']).sum() / bars['Volume'].sum()
            std_dev = np.sqrt(variance)
            
            return {
                'vwap': vwap,
                'upper': round(vwap + std_dev * config.vwap_std_dev_multiplier, 2),
                'lower': round(vwap - std_dev * config.vwap_std_dev_multiplier, 2),
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
            
            bars = bars.loc[bars.index.date == self.clock().date()]
            or_bars = bars.between_time('09:30', '09:45', inclusive='left')
            if or_bars.empty:
                return None
            
            or_high = or_bars['High'].max()
            or_low = or_bars['Low'].min()
            or_range_pct = (or_high - or_low) / or_low * 100 if or_low > 0 else 0
            
            return {
                'high': or_high,
                'low': or_low,
                'range_pct': or_range_pct,
                'is_narrow': or_range_pct < config.or_narrow_threshold,
                'is_wide': or_range_pct > config.or_wide_threshold,
            }
        except Exception as e:
            logger.error(f"OR calc failed for {symbol}: {e}")
            return None
    
    def is_execution_window(self) -> bool:
        """Check if current time is in institutional execution window."""
        now = self.clock().time()
        # Morning window: 9:45-11:00 AM ET
        morning = config.morning_window_start <= now <= config.morning_window_end
        # Afternoon window: 2:00-3:30 PM ET
        afternoon = config.afternoon_window_start <= now <= config.afternoon_window_end
        return morning or afternoon
    
    def generate_signal(self, symbol: str) -> Optional[Signal]:
        """Generate a signal using multi-factor scoring."""
        try:
            price = self.data_feed.get_latest_price(symbol)
            if not price:
                return None
            
            vwap_bands = self.calculate_vwap_bands(symbol)
            or_data = self.calculate_opening_range(symbol)
            volume_ratio = self.data_feed.get_volume_ratio(symbol)
            adx = self.data_feed.get_adx(symbol)
            
            if not all([vwap_bands, or_data, volume_ratio]):
                return None
            
            vwap = vwap_bands['vwap']
            upper_band = vwap_bands['upper']
            lower_band = vwap_bands['lower']
            
            # ─── Scoring ────────────────────────────────────────────
            score = 0
            direction = None
            
            # Factor 1: VWAP deviation
            if price <= lower_band:
                score += 2
                direction = SignalDirection.LONG
            elif price >= upper_band:
                score += 2
                direction = SignalDirection.SHORT
            
            # Factor 2: Volume confirmation
            if volume_ratio >= config.min_volume_mult:
                score += 2
            elif volume_ratio >= 1.0:
                score += 1
            
            # Factor 3: Narrow opening range
            if or_data['is_narrow']:
                score += 1
            
            # Factor 4: Execution window
            if self.is_execution_window():
                score += 1
            
            # Factor 5: Price reverts through VWAP
            if direction == SignalDirection.LONG and price > vwap:
                score += 2
            elif direction == SignalDirection.SHORT and price < vwap:
                score += 2
            
            # Factor 6: ADX trend filter
            if config.regime_filter and adx:
                if adx >= config.adx_trend_threshold:
                    score += 1  # Bonus for trending market
                elif adx < 15:
                    score -= 1  # Penalty for choppy market
            
            # ─── Minimum Score Gate ─────────────────────────────────
            if direction is None or score < config.min_score_to_trade:
                return None
            
            # ─── Calculate Stop/Target ──────────────────────────────
            atr = self.data_feed.get_atr(symbol, config.atr_length) or (price * 0.005)
            stop_distance = atr * config.atr_stop_multiplier
            
            if direction == SignalDirection.LONG:
                price = round(price, 2)
                stop = round(price - stop_distance, 2)
                target = round(price + (price - stop) * config.rr_ratio, 2)
            else:
                price = round(price, 2)
                stop = round(price + stop_distance, 2)
                target = round(price - (stop - price) * config.rr_ratio, 2)
            
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
                adx=adx,
            )
            
        except Exception as e:
            logger.error(f"Signal generation error for {symbol}: {e}")
            return None
    
    def generate_all_signals(self) -> List[Signal]:
        """Generate signals for all symbols."""
        signals = []
        for symbol in config.universe:
            if symbol in self.positions:
                continue
            signal = self.generate_signal(symbol)
            if signal:
                signals.append(signal)
        signals.sort(key=lambda x: x.score, reverse=True)
        return signals
    
    def add_position(self, symbol: str, direction: SignalDirection, price: float, shares: float, stop: float, target: float):
        """Add a new position."""
        self.positions[symbol] = Position(
            symbol=symbol,
            direction=direction,
            entry_price=price,
            shares=shares,
            stop=stop,
            target=target,
        )
    
    def update_positions(self, symbol: str, current_price: float):
        """Update trailing stops and check exits."""
        if symbol not in self.positions:
            return None
        
        position = self.positions[symbol]
        atr = self.data_feed.get_atr(symbol, config.atr_length) or current_price * 0.005
        position.update_trailing_stop(current_price, atr)
        
        should_exit, reason = position.should_exit(current_price)
        if should_exit:
            return {
                'symbol': symbol,
                'exit_price': current_price,
                'reason': reason,
                'pnl': (current_price - position.entry_price) * position.shares if position.direction == SignalDirection.LONG else (position.entry_price - current_price) * position.shares,
            }
        
        return None
    
    def close_position(self, symbol: str):
        """Close a position."""
        if symbol in self.positions:
            del self.positions[symbol]
    
    def check_max_drawdown(self, current_equity: float) -> bool:
        """Check if max drawdown exceeded."""
        if current_equity > self.portfolio_peak:
            self.portfolio_peak = current_equity
        drawdown = ((self.portfolio_peak - current_equity) / self.portfolio_peak) * 100
        return drawdown >= config.max_drawdown_pct
    
    def check_sector_exposure(self, symbol: str) -> bool:
        """Check if adding this symbol would exceed sector limits."""
        tech_count = sum(1 for s in self.positions if s in config.tech_symbols)
        if symbol in config.tech_symbols:
            tech_count += 1
        max_tech = int(len(config.tech_symbols) * config.max_sector_exposure)
        return tech_count <= max_tech
