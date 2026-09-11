#!/usr/bin/env python3
"""
Alpaca trade execution engine.
Fetches real prices and executes real trades via Alpaca API.
"""
import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from alpaca.trading.client import TradingClient
from alpaca.common.exceptions import APIError
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest, OrderRequest,
    TakeProfitRequest, StopLossRequest,
    GetOrdersRequest, GetOrderByIdRequest
)
from alpaca.trading.enums import (
    OrderSide, TimeInForce, OrderType, QueryOrderStatus,
    OrderClass
)
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from config import config
from models import FillResult, FillStatus, OrderSide as SignalSide

logger = logging.getLogger(__name__)


class AlpacaTrader:
    """Execute trades via Alpaca API."""
    
    def __init__(self):
        self.api_key = os.getenv('ALPACA_API_KEY')
        self.secret_key = os.getenv('ALPACA_SECRET_KEY')
        self.paper = os.getenv('PAPER_TRADING', 'true').lower() == 'true'
        
        self.trading_client = None
        self.data_client = None
        self._initialized = False
    
    def _ensure_initialized(self):
        """Lazy initialization of Alpaca clients."""
        if self._initialized:
            return
        try:
            self.trading_client = TradingClient(self.api_key, self.secret_key, paper=self.paper)
            self.data_client = StockHistoricalDataClient(self.api_key, self.secret_key)
            self._initialized = True
            logger.info(f"Alpaca client initialized (paper={self.paper})")
        except Exception as e:
            logger.error(f"Alpaca client init failed: {e}")
    
    def get_account(self) -> Optional[dict]:
        """Get account details."""
        self._ensure_initialized()
        if not self.trading_client:
            return None
        try:
            account = self.trading_client.get_account()
            return {
                'equity': float(account.equity),
                'buying_power': float(account.buying_power),
                'cash': float(account.cash),
                'portfolio_value': float(account.portfolio_value),
                'pattern_day_trader': account.pattern_day_trader,
                'trading_blocked': account.trading_blocked,
                'daytrade_count': account.daytrade_count,
                'status': account.status.value,
            }
        except Exception as e:
            logger.error(f"Account fetch failed: {e}")
            return None
    
    def get_positions(self, strict: bool = False) -> List[dict]:
        """Get all open positions."""
        self._ensure_initialized()
        if not self.trading_client:
            if strict:
                raise RuntimeError("Alpaca client unavailable")
            return []
        try:
            positions = self.trading_client.get_all_positions()
            return [{
                'symbol': p.symbol,
                'qty': abs(float(p.qty)),
                'side': p.side.value,
                'entry_price': float(p.avg_entry_price),
                'current_price': float(p.current_price),
                'market_value': float(p.market_value),
                'unrealized_pl': float(p.unrealized_pl),
                'unrealized_plpc': float(p.unrealized_plpc),
            } for p in positions]
        except Exception as e:
            logger.error(f"Positions fetch failed: {e}")
            if strict:
                raise
            return []
    
    def get_position(self, symbol: str) -> Optional[dict]:
        """Get position for a specific symbol."""
        self._ensure_initialized()
        if not self.trading_client:
            return None
        try:
            p = self.trading_client.get_open_position(symbol)
            return {
                'symbol': p.symbol,
                'qty': abs(float(p.qty)),
                'side': p.side.value,
                'entry_price': float(p.avg_entry_price),
                'current_price': float(p.current_price),
                'market_value': float(p.market_value),
                'unrealized_pl': float(p.unrealized_pl),
                'unrealized_plpc': float(p.unrealized_plpc),
            }
        except Exception as e:
            logger.debug(f"No position for {symbol}: {e}")
            return None
    
    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Get latest mid-price."""
        self._ensure_initialized()
        if not self.data_client:
            return None
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
            quotes = self.data_client.get_stock_latest_quote(request)
            quote = quotes[symbol]
            return round((quote.ask_price + quote.bid_price) / 2, 2)
        except Exception as e:
            logger.error(f"Price fetch failed for {symbol}: {e}")
            return None
    
    def get_bars(self, symbol: str, days: int = 5):
        """Get recent price bars."""
        self._ensure_initialized()
        if not self.data_client:
            return None
        try:
            end = datetime.now()
            start = end - timedelta(days=days + 5)
            
            request = StockBarsRequest(
                symbol_or_symbols=[symbol],
                timeframe=TimeFrame.Minute,
                start=start,
                end=end,
            )
            bars = self.data_client.get_stock_bars(request)
            if symbol in bars and not bars[symbol].df.empty:
                df = bars[symbol].df.copy()
                df.index = df.index.tz_localize(None) if df.index.tz else df.index
                return df
            return None
        except Exception as e:
            logger.error(f"Bars fetch failed for {symbol}: {e}")
            return None
    
    def get_atr(self, symbol: str, period: int = 14) -> Optional[float]:
        """Get the Average True Range."""
        self._ensure_initialized()
        if not self.data_client:
            return None
        try:
            bars = self.get_bars(symbol, days=5)
            if bars is None or len(bars) < period:
                return None
            
            high = bars['high']
            low = bars['low']
            prev_close = bars['close'].shift(1)
            
            import pandas as pd
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
    
    def submit_market_order(
        self,
        symbol: str,
        qty: int,
        side: SignalSide,
        time_in_force: TimeInForce = TimeInForce.DAY,
        client_order_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Submit a market order."""
        self._ensure_initialized()
        if not self.trading_client:
            return None
        try:
            order_side = OrderSide(SignalSide(side).value)
            order = self.trading_client.submit_order(MarketOrderRequest(
                symbol=symbol,
                client_order_id=client_order_id,
                qty=qty,
                side=order_side,
                time_in_force=time_in_force,
            ))
            logger.info(f"Market order submitted: {symbol} {side.value} x{qty}")
            return {
                'id': str(order.id),
                'symbol': order.symbol,
                'side': order.side.value,
                'qty': int(order.qty),
                'type': order.type.value,
                'status': order.status.value,
                'submitted_at': order.submitted_at,
            }
        except Exception as e:
            logger.error(f"Market order failed: {symbol} {side.value} x{qty}: {e}")
            return None
    
    def submit_bracket_order(
        self,
        symbol: str,
        qty: int,
        side: SignalSide,
        stop_price: float,
        target_price: float,
        client_order_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Submit a bracket order (entry + stop loss + take profit)."""
        self._ensure_initialized()
        if not self.trading_client:
            return None
        try:
            order_side = OrderSide(SignalSide(side).value)
            
            # Use OrderRequest with OrderClass.BRACKET
            order = self.trading_client.submit_order(OrderRequest(
                symbol=symbol,
                client_order_id=client_order_id,
                qty=qty,
                side=order_side,
                type=OrderType.MARKET,
                time_in_force=TimeInForce.GTC,
                order_class=OrderClass.BRACKET,
                take_profit=TakeProfitRequest(limit_price=target_price),
                stop_loss=StopLossRequest(stop_price=stop_price),
            ))
            logger.info(f"Bracket order submitted: {symbol} {side.value} x{qty} | Stop: ${stop_price} | Target: ${target_price}")
            return {
                'id': str(order.id),
                'symbol': order.symbol,
                'side': order.side.value,
                'qty': int(order.qty),
                'type': order.type.value,
                'status': order.status.value,
                'submitted_at': order.submitted_at,
            }
        except Exception as e:
            logger.error(f"Bracket order failed: {symbol} {side.value} x{qty}: {e}")
            return None
    
    def close_position(self, symbol: str) -> Optional[dict]:
        """Close a position."""
        self._ensure_initialized()
        if not self.trading_client:
            return None
        try:
            order = self.trading_client.close_position(symbol)
            logger.info(f"Position closed: {symbol}")
            return {
                'id': str(order.id),
                'symbol': order.symbol,
                'side': order.side.value,
                'qty': int(order.qty),
                'status': order.status.value,
            }
        except Exception as e:
            logger.error(f"Close failed for {symbol}: {e}")
            return None
    
    def close_all_positions(self):
        """Close all positions."""
        self._ensure_initialized()
        if not self.trading_client:
            return
        try:
            self.trading_client.close_all_positions()
            logger.info("All positions closed")
        except Exception as e:
            logger.error(f"Close all failed: {e}")
    
    def cancel_all_orders(self):
        """Cancel all open orders."""
        self._ensure_initialized()
        if not self.trading_client:
            return
        try:
            self.trading_client.cancel_orders()
            logger.info("All orders cancelled")
        except Exception as e:
            logger.error(f"Cancel all failed: {e}")
    
    def get_orders(self, status: str = "open") -> List[dict]:
        """Get orders by status."""
        self._ensure_initialized()
        if not self.trading_client:
            return []
        try:
            if status == "open":
                request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            elif status == "closed":
                request = GetOrdersRequest(status=QueryOrderStatus.CLOSED)
            else:
                request = GetOrdersRequest()
            
            orders = self.trading_client.get_orders(request)
            return [{
                'id': o.id,
                'symbol': o.symbol,
                'side': o.side.value,
                'type': o.type.value,
                'qty': int(o.qty),
                'filled_qty': int(o.filled_qty) if o.filled_qty else 0,
                'limit_price': float(o.limit_price) if o.limit_price else None,
                'stop_price': float(o.stop_price) if o.stop_price else None,
                'filled_avg_price': float(o.filled_avg_price) if o.filled_avg_price else None,
                'status': o.status.value,
                'submitted_at': o.submitted_at,
                'filled_at': o.filled_at,
            } for o in orders]
        except Exception as e:
            logger.error(f"Orders fetch failed: {e}")
            return []
    
    def is_market_open(self) -> bool:
        """Check if the market is open."""
        self._ensure_initialized()
        if not self.trading_client:
            return False
        try:
            clock = self.trading_client.get_clock()
            return clock.is_open
        except Exception as e:
            logger.error(f"Clock check failed: {e}")
            return False
    
    def get_clock(self) -> Optional[dict]:
        """Get market clock."""
        self._ensure_initialized()
        if not self.trading_client:
            return None
        try:
            clock = self.trading_client.get_clock()
            return {
                'is_open': clock.is_open,
                'next_open': str(clock.next_open),
                'next_close': str(clock.next_close),
                'timestamp': str(clock.timestamp),
            }
        except Exception as e:
            logger.error(f"Clock fetch failed: {e}")
            return None

    @staticmethod
    def _order_record(order):
        return {
            'id': str(order.id), 'client_order_id': order.client_order_id,
            'symbol': order.symbol, 'side': order.side.value,
            'status': order.status.value, 'qty': float(order.qty or 0),
            'filled_qty': float(order.filled_qty or 0),
            'filled_avg_price': float(order.filled_avg_price or 0),
            'filled_at': order.filled_at.isoformat() if order.filled_at else None,
            'stop_price': float(order.stop_price) if order.stop_price else None,
            'limit_price': float(order.limit_price) if order.limit_price else None,
            'legs': [AlpacaTrader._order_record(leg) for leg in order.legs or []],
        }

    def get_order(self, order_id):
        self._ensure_initialized()
        if not self.trading_client:
            raise RuntimeError('Alpaca client unavailable')
        return self._order_record(self.trading_client.get_order_by_id(
            order_id, filter=GetOrderByIdRequest(nested=True)))

    def get_order_by_client_id(self, client_id):
        self._ensure_initialized()
        if not self.trading_client:
            raise RuntimeError('Alpaca client unavailable')
        try:
            order = self.trading_client.get_order_by_client_id(client_id)
            return self.get_order(str(order.id))
        except APIError as exc:
            if exc.status_code == 404:
                return None
            raise

    def open_orders(self, symbol=None):
        """Strict read: an outage must not look like an empty order book."""
        self._ensure_initialized()
        if not self.trading_client:
            raise RuntimeError('Alpaca client unavailable')
        request = GetOrdersRequest(status=QueryOrderStatus.OPEN, nested=False,
                                   symbols=[symbol] if symbol else None, limit=500)
        return [self._order_record(o) for o in self.trading_client.get_orders(request)]

    def cancel_symbol_orders(self, symbol):
        """Request cancellation; callers must confirm absence before closing."""
        for order in self.open_orders(symbol):
            self.trading_client.cancel_order_by_id(order['id'])
