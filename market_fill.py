#!/usr/bin/env python3
"""
Market fill engine with realistic slippage, commission, and partial fills.
"""
import random
import logging
from datetime import datetime
from typing import Optional, Tuple

from models import FillResult, FillStatus, OrderSide

logger = logging.getLogger(__name__)


class MarketFillEngine:
    """
    Simulates realistic market fills with:
    - Slippage based on volatility and order size
    - Commission (Alpaca: $0, but we track for realism)
    - Partial fills for large orders
    - Rejection for extreme orders
    """
    
    # Slippage parameters (basis points)
    BASE_SLIPPAGE_BPS = 1.0      # 0.01% base slippage
    VOLATILITY_SLIPPAGE = 0.5    # Additional per 1% volatility
    SIZE_IMPACT_BPS = 0.1        # Per 100 shares
    
    # Commission (Alpaca is commission-free, but track for realism)
    COMMISSION_PER_SHARE = 0.0   # Alpaca: $0
    MIN_COMMISSION = 0.0
    
    # Fill probability
    FILL_PROBABILITY = 0.98      # 98% fill rate for market orders
    PARTIAL_FILL_PROBABILITY = 0.05  # 5% partial fill for large orders
    
    def __init__(self, volatility_lookback: int = 20):
        self.volatility_lookback = volatility_lookback
    
    def calculate_slippage(
        self, 
        price: float, 
        size: int, 
        side: OrderSide,
        atr: Optional[float] = None,
        spread: Optional[float] = None
    ) -> float:
        """Calculate realistic slippage in dollars."""
        # Base slippage
        slippage_bps = self.BASE_SLIPPAGE_BPS
        
        # Volatility component (higher vol = more slippage)
        if atr and price > 0:
            vol_pct = (atr / price) * 100
            slippage_bps += vol_pct * self.VOLATILITY_SLIPPAGE
        
        # Size impact (larger orders move the market)
        size_units = max(1, size // 100)
        slippage_bps += size_units * self.SIZE_IMPACT_BPS
        
        # Spread component (half the spread is typical)
        if spread:
            slippage_bps += (spread / price) * 10000 * 0.5
        
        # Random component (±30%)
        random_factor = random.uniform(0.7, 1.3)
        slippage_bps *= random_factor
        
        # Convert to dollars
        slippage = price * (slippage_bps / 10000)
        
        # Minimum slippage: $0.01
        return max(0.01, round(slippage, 2))
    
    def fill_market_order(
        self,
        symbol: str,
        side: OrderSide,
        size: int,
        current_price: float,
        atr: Optional[float] = None,
        spread: Optional[float] = None
    ) -> FillResult:
        """Simulate a market order fill."""
        # Check for rejection (very rare)
        if random.random() > self.FILL_PROBABILITY:
            return FillResult(
                symbol=symbol,
                side=side,
                requested_price=current_price,
                fill_price=0.0,
                size=0,
                slippage=0.0,
                commission=0.0,
                status=FillStatus.REJECTED,
                reason="Liquidity insufficient",
                timestamp=datetime.utcnow()
            )
        
        # Calculate slippage
        slippage = self.calculate_slippage(current_price, size, side, atr, spread)
        
        # Apply slippage (buy higher, sell lower)
        if side == OrderSide.BUY:
            fill_price = current_price + slippage
        else:
            fill_price = current_price - slippage
        
        # Check for partial fill (large orders)
        actual_size = size
        if size > 50 and random.random() < self.PARTIAL_FILL_PROBABILITY:
            fill_pct = random.uniform(0.5, 0.9)
            actual_size = max(1, int(size * fill_pct))
            logger.info(f"Partial fill: {symbol} {actual_size}/{size} shares")
        
        # Commission
        commission = max(self.MIN_COMMISSION, actual_size * self.COMMISSION_PER_SHARE)
        
        return FillResult(
            symbol=symbol,
            side=side,
            requested_price=current_price,
            fill_price=round(fill_price, 2),
            size=actual_size,
            slippage=slippage,
            commission=commission,
            status=FillStatus.FILLED,
            timestamp=datetime.utcnow()
        )
    
    def fill_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        size: int,
        limit_price: float,
        current_price: float,
        atr: Optional[float] = None
    ) -> FillResult:
        """Simulate a limit order fill."""
        # Check if limit is reachable
        if side == OrderSide.BUY and limit_price < current_price:
            return FillResult(
                symbol=symbol,
                side=side,
                requested_price=limit_price,
                fill_price=0.0,
                size=0,
                slippage=0.0,
                commission=0.0,
                status=FillStatus.PENDING,
                reason="Limit below market"
            )
        elif side == OrderSide.SELL and limit_price > current_price:
            return FillResult(
                symbol=symbol,
                side=side,
                requested_price=limit_price,
                fill_price=0.0,
                size=0,
                slippage=0.0,
                commission=0.0,
                status=FillStatus.PENDING,
                reason="Limit above market"
            )
        
        # Fill at limit price (no slippage for limit orders)
        commission = max(self.MIN_COMMISSION, size * self.COMMISSION_PER_SHARE)
        
        return FillResult(
            symbol=symbol,
            side=side,
            requested_price=limit_price,
            fill_price=limit_price,
            size=size,
            slippage=0.0,
            commission=commission,
            status=FillStatus.FILLED,
            timestamp=datetime.utcnow()
        )
    
    def check_stop_hit(
        self,
        stop_price: float,
        current_price: float,
        side: OrderSide,
        high: float,
        low: float
    ) -> Tuple[bool, float]:
        """Check if stop loss was hit and return fill price."""
        if side == OrderSide.BUY:
            # Long position: stop is below entry
            if low <= stop_price:
                # Gap down through stop
                if open < stop_price:
                    return True, stop_price * 0.995  # Gap fill worse
                return True, stop_price
        else:
            # Short position: stop is above entry
            if high >= stop_price:
                # Gap up through stop
                if open > stop_price:
                    return True, stop_price * 1.005  # Gap fill worse
                return True, stop_price
        
        return False, 0.0
    
    def check_target_hit(
        self,
        target_price: float,
        current_price: float,
        side: OrderSide,
        high: float,
        low: float
    ) -> Tuple[bool, float]:
        """Check if take profit was hit and return fill price."""
        if side == OrderSide.BUY:
            # Long position: target is above entry
            if high >= target_price:
                return True, target_price
        else:
            # Short position: target is below entry
            if low <= target_price:
                return True, target_price
        
        return False, 0.0
