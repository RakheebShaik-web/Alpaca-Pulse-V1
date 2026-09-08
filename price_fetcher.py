#!/usr/bin/env python3
"""
Real-time price fetcher using Alpaca API.
"""
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

from config import config

logger = logging.getLogger(__name__)


class PriceFetcher:
    """Fetch real-time and historical prices from Alpaca."""
    
    def __init__(self):
        self.api_key = os.getenv('ALPACA_API_KEY')
        self.secret_key = os.getenv('ALPACA_SECRET_KEY')
        self.paper = os.getenv('PAPER_TRADING', 'true').lower() == 'true'
        
        self.data_client = StockHistoricalDataClient(self.api_key, self.secret_key)
        self.trading_client = TradingClient(self.api_key, self.secret_key, paper=self.paper)
    
    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Get the latest mid-price for a symbol."""
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
            quotes = self.data_client.get_stock_latest_quote(request)
            quote = quotes[symbol]
            mid_price = (quote.ask_price + quote.bid_price) / 2
            return round(mid_price, 2)
        except Exception as e:
            logger.error(f"Failed to get price for {symbol}: {e}")
            return None
    
    def get_latest_trade(self, symbol: str) -> Optional[float]:
        """Get the latest trade price."""
        try:
            request = StockLatestTradeRequest(symbol_or_symbols=[symbol])
            trades = self.data_client.get_stock_latest_trade(request)
            return round(trades[symbol].price, 2)
        except Exception as e:
            logger.error(f"Failed to get trade for {symbol}: {e}")
            return None
    
    def get_spread(self, symbol: str) -> Optional[float]:
        """Get the current bid-ask spread."""
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
            quotes = self.data_client.get_stock_latest_quote(request)
            quote = quotes[symbol]
            return round(quote.ask_price - quote.bid_price, 2)
        except Exception as e:
            logger.error(f"Failed to get spread for {symbol}: {e}")
            return None
    
    def get_bars(self, symbol: str, days: int = 5) -> Optional[dict]:
        """Get recent price bars."""
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
            logger.error(f"Failed to get bars for {symbol}: {e}")
            return None
    
    def get_vwap(self, symbol: str) -> Optional[float]:
        """Get the current session VWAP."""
        try:
            bars = self.get_bars(symbol, days=1)
            if bars is None or bars.empty:
                return None
            
            typical_price = (bars['high'] + bars['low'] + bars['close']) / 3
            vwap = (typical_price * bars['volume']).sum() / bars['volume'].sum()
            return round(vwap, 2)
        except Exception as e:
            logger.error(f"Failed to get VWAP for {symbol}: {e}")
            return None
    
    def get_atr(self, symbol: str, period: int = 14) -> Optional[float]:
        """Get the Average True Range."""
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
    
    def get_multiple_prices(self, symbols: List[str]) -> Dict[str, float]:
        """Get latest prices for multiple symbols."""
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=symbols)
            quotes = self.data_client.get_stock_latest_quote(request)
            prices = {}
            for symbol in symbols:
                if symbol in quotes:
                    q = quotes[symbol]
                    prices[symbol] = round((q.ask_price + q.bid_price) / 2, 2)
            return prices
        except Exception as e:
            logger.error(f"Failed to get multiple prices: {e}")
            return {}
    
    def get_account_info(self) -> Optional[dict]:
        """Get account information."""
        try:
            account = self.trading_client.get_account()
            return {
                'equity': float(account.equity),
                'buying_power': float(account.buying_power),
                'cash': float(account.cash),
                'portfolio_value': float(account.portfolio_value),
                'pattern_day_trader': account.pattern_day_trader,
                'trading_blocked': account.trading_blocked,
            }
        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            return None
    
    def get_positions(self) -> List[dict]:
        """Get current positions."""
        try:
            positions = self.trading_client.get_all_positions()
            return [{
                'symbol': p.symbol,
                'qty': int(p.qty),
                'side': p.side.value,
                'entry_price': float(p.avg_entry_price),
                'current_price': float(p.current_price),
                'market_value': float(p.market_value),
                'unrealized_pl': float(p.unrealized_pl),
                'unrealized_plpc': float(p.unrealized_plpc),
            } for p in positions]
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []
    
    def get_open_orders(self) -> List[dict]:
        """Get open orders."""
        try:
            request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            orders = self.trading_client.get_orders(request)
            return [{
                'id': o.id,
                'symbol': o.symbol,
                'side': o.side.value,
                'type': o.type.value,
                'qty': int(o.qty),
                'limit_price': float(o.limit_price) if o.limit_price else None,
                'stop_price': float(o.stop_price) if o.stop_price else None,
                'submitted_at': o.submitted_at,
            } for o in orders]
        except Exception as e:
            logger.error(f"Failed to get orders: {e}")
            return []
    
    def cancel_all_orders(self):
        """Cancel all open orders."""
        try:
            self.trading_client.cancel_orders()
            logger.info("All orders cancelled")
        except Exception as e:
            logger.error(f"Failed to cancel orders: {e}")
