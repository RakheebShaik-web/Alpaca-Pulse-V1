#!/usr/bin/env python3
"""
Live trading bot for Alpaca with Discord alerts.
Pre-Market Momentum + Opening Range Breakout.
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta, time as dtime

from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest, GetOrdersRequest,
    GetCalendarRequest
)
from alpaca.trading.enums import (
    OrderSide, TimeInForce, OrderType, QueryOrderStatus
)
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from config import config
from discord_notifier import DiscordNotifier

load_dotenv()

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('trading.log'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


class LiveTrader:
    def __init__(self):
        self.api_key = os.getenv('ALPACA_API_KEY')
        self.secret_key = os.getenv('ALPACA_SECRET_KEY')
        self.paper = os.getenv('PAPER_TRADING', 'true').lower() == 'true'
        self.discord_webhook = os.getenv('DISCORD_WEBHOOK_URL', '')
        
        self.trading_client = TradingClient(
            self.api_key, self.secret_key, paper=self.paper
        )
        self.data_client = StockHistoricalDataClient(self.api_key, self.secret_key)
        self.notifier = DiscordNotifier(self.discord_webhook)
        
        self.active_trades = {}
        self.todays_setups = []
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.current_date = None
        
        # State
        self.or_high = None
        self.or_low = None
        self.pm_high = None
        self.pm_low = None
        self.pm_open = None
        self.prev_close = None
    
    def verify_account(self):
        """Verify account access and buying power."""
        try:
            account = self.trading_client.get_account()
            equity = float(account.equity)
            buying_power = float(account.buying_power)
            logger.info(f"Account verified | Equity: ${equity:,.2f} | "
                       f"Buying Power: ${buying_power:,.2f} | "
                       f"{'PAPER' if self.paper else 'LIVE'}")
            self.notifier.send(
                f"**Trader Started** | {'PAPER' if self.paper else 'LIVE'} | "
                f"Equity: ${equity:,.2f}"
            )
            return True
        except Exception as e:
            logger.error(f"Account verification failed: {e}")
            return False
    
    def reset_daily(self, date):
        """Reset daily counters."""
        if date != self.current_date:
            # Send summary for previous day
            if self.current_date is not None:
                self.notifier.send_daily_summary({
                    'date': str(self.current_date),
                    'trades': self.trades_today,
                    'win_rate': 0,  # Would need to track wins
                    'daily_pnl': self.daily_pnl,
                    'portfolio': self._get_portfolio_value(),
                })
            
            self.current_date = date
            self.daily_pnl = 0.0
            self.trades_today = 0
            self.todays_setups = []
            self.or_high = None
            self.or_low = None
            self.pm_high = None
            self.pm_low = None
            self.pm_open = None
            self.prev_close = None
            logger.info("--- DAILY COUNTERS RESET ---")
    
    def _get_portfolio_value(self) -> float:
        """Get current portfolio value."""
        try:
            account = self.trading_client.get_account()
            return float(account.equity)
        except:
            return 0.0
    
    def can_trade(self) -> bool:
        """Check if we can still trade today."""
        if self.trades_today >= config.max_trades_per_day:
            logger.warning("Max trades reached")
            return False
        if self.daily_pnl <= -config.max_daily_loss:
            logger.warning("Max daily loss reached")
            return False
        if self.daily_pnl >= config.target_daily_pnl:
            logger.info("Daily target reached")
            return False
        return True
    
    def get_position_size(self, entry: float, stop: float) -> int:
        """Calculate position size based on $50 risk."""
        risk_per_share = abs(entry - stop)
        if risk_per_share <= 0:
            return 0
        size = int(config.risk_per_trade / risk_per_share)
        # Cap at 20% of capital
        max_size = int(config.capital * 0.2 / entry)
        return max(1, min(size, max_size))
    
    def get_current_price(self, symbol: str) -> float:
        """Get mid price from latest quote."""
        request = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
        quotes = self.data_client.get_stock_latest_quote(request)
        quote = quotes[symbol]
        return (quote.ask_price + quote.bid_price) / 2
    
    def get_previous_close(self, symbol: str) -> float:
        """Get previous trading day's close."""
        end = datetime.now()
        start = end - timedelta(days=5)  # Look back up to 5 days
        
        request = StockBarsRequest(
            symbol_or_symbols=[symbol],
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
        )
        try:
            bars = self.data_client.get_stock_bars(request)
            if symbol in bars and not bars[symbol].df.empty:
                df = bars[symbol].df
                df.index = df.index.tz_localize(None) if df.index.tz else df.index
                # Get the most recent daily close
                return float(df['close'].iloc[-1])
        except:
            pass
        return 0.0
    
    def scan_setups(self) -> list:
        """Scan for pre-market momentum setups."""
        setups = []
        end = datetime.now()
        start = end.replace(hour=4, minute=0, second=0, microsecond=0)
        
        for symbol in config.universe:
            try:
                request = StockBarsRequest(
                    symbol_or_symbols=[symbol],
                    timeframe=TimeFrame.Minute,
                    start=start,
                    end=end,
                )
                bars = self.data_client.get_stock_bars(request)
                if symbol not in bars or bars[symbol].df.empty:
                    continue
                
                df = bars[symbol].df.copy()
                df.index = df.index.tz_localize(None) if df.index.tz else df.index
                
                # Pre-market metrics
                pm_high = df['high'].max()
                pm_low = df['low'].min()
                pm_volume = int(df['volume'].sum())
                pm_open = float(df['open'].iloc[0])
                
                # Get previous close
                prev_close = self.get_previous_close(symbol)
                if prev_close <= 0:
                    continue
                
                gap_pct = (pm_open - prev_close) / prev_close
                
                if abs(gap_pct) >= config.gap_threshold and pm_volume >= config.min_premarket_volume:
                    setups.append({
                        'symbol': symbol,
                        'direction': 'long' if gap_pct > 0 else 'short',
                        'gap_pct': gap_pct,
                        'pm_high': pm_high,
                        'pm_low': pm_low,
                        'pm_volume': pm_volume,
                        'pm_open': pm_open,
                        'prev_close': prev_close,
                    })
                    logger.info(
                        f"SETUP: {symbol:6s} | Gap: {gap_pct:+.2%} | "
                        f"Vol: {pm_volume:>10,} | Dir: {'LONG' if gap_pct > 0 else 'SHORT'}"
                    )
            except Exception as e:
                logger.debug(f"Scan error for {symbol}: {e}")
        
        # Sort by absolute gap (trade the biggest movers first)
        setups.sort(key=lambda x: abs(x['gap_pct']), reverse=True)
        return setups
    
    def submit_entry(self, symbol: str, side: OrderSide, 
                     entry: float, stop: float, tp: float, qty: int):
        """Submit bracket order."""
        try:
            # Market entry
            order = self.trading_client.submit_order(MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side,
                time_in_force=TimeInForce.DAY,
            ))
            logger.info(f"Entry submitted: {symbol} {side.name} x{qty}")
            
            # Attach stop loss
            exit_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
            self.trading_client.submit_order(MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=exit_side,
                time_in_force=TimeInForce.DAY,
                extra={'stop_price': round(stop, 2)},
            ))
            
            # Attach take profit
            self.trading_client.submit_order(LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=exit_side,
                limit_price=round(tp, 2),
                time_in_force=TimeInForce.DAY,
            ))
            
            self.trades_today += 1
            self.active_trades[symbol] = {
                'side': side.name,
                'entry': entry,
                'stop': stop,
                'tp': tp,
                'qty': qty,
            }
            logger.info(f"BRACKET ORDER: {symbol} | Entry: ${entry:.2f} | "
                       f"Stop: ${stop:.2f} | TP: ${tp:.2f} | Qty: {qty}")
            
            # Discord alert
            self.notifier.send_trade_alert({
                'symbol': symbol,
                'direction': 'LONG' if side == OrderSide.BUY else 'SHORT',
                'entry': entry,
                'stop': stop,
                'tp': tp,
                'size': qty,
                'risk': abs(entry - stop) * qty,
                'gap_pct': 0,
            })
            return True
            
        except Exception as e:
            logger.error(f"Order failed: {e}")
            return False
    
    def close_position(self, symbol: str):
        """Close a position."""
        try:
            self.trading_client.close_position(symbol)
            logger.info(f"Position closed: {symbol}")
            self.active_trades.pop(symbol, None)
        except Exception as e:
            logger.error(f"Close failed: {e}")
    
    def close_all(self):
        """Close all positions."""
        try:
            self.trading_client.close_all_positions()
            logger.info("All positions closed")
            self.active_trades.clear()
        except Exception as e:
            logger.error(f"Close all failed: {e}")
    
    def execute_setups(self):
        """Execute today's pre-market setups."""
        for setup in self.todays_setups:
            if not self.can_trade():
                break
            
            symbol = setup['symbol']
            
            # Skip if already in position
            try:
                self.trading_client.get_open_position(symbol)
                continue
            except:
                pass
            
            try:
                price = self.get_current_price(symbol)
            except Exception as e:
                logger.error(f"Quote error for {symbol}: {e}")
                continue
            
            direction = setup['direction']
            
            if direction == 'long':
                stop = price * 0.995  # 0.5% stop
                risk = price - stop
                tp = price + (risk * config.rr_ratio)
                side = OrderSide.BUY
            else:
                stop = price * 1.005
                risk = stop - price
                tp = price - (risk * config.rr_ratio)
                side = OrderSide.SELL
            
            qty = self.get_position_size(price, stop)
            if qty > 0:
                self.submit_entry(symbol, side, price, stop, tp, qty)
    
    def run(self):
        """Main loop."""
        mode = "PAPER" if self.paper else "LIVE"
        logger.info("=" * 60)
        logger.info(f"TRADER STARTED | {mode} | ${config.capital:,.0f}")
        logger.info("=" * 60)
        
        if not self.verify_account():
            return
        
        while True:
            now = datetime.now()
            self.reset_daily(now.date())
            
            current_time = now.time()
            
            # === PRE-MARKET SCAN (4:00-9:30 AM) ===
            if dtime(4, 0) <= current_time < dtime(9, 30):
                # Scan once per hour to avoid rate limits
                if now.minute < 5:
                    self.todays_setups = self.scan_setups()
                    logger.info(f"Scan complete: {len(self.todays_setups)} setup(s)")
                    
                    # Send scan results to Discord
                    if self.todays_setups:
                        self.notifier.send_scan_results(self.todays_setups)
            
            # === TRADING HOURS (9:30-11:00 AM) ===
            elif dtime(9, 30) <= current_time < dtime(11, 0):
                # Execute at market open
                if not self.active_trades and self.todays_setups:
                    self.execute_setups()
                    self.todays_setups = []
                
                # Manage exits
                for symbol in list(self.active_trades.keys()):
                    try:
                        pos = self.trading_client.get_open_position(symbol)
                        if not pos:
                            self.active_trades.pop(symbol, None)
                    except:
                        self.active_trades.pop(symbol, None)
            
            # === POST-TRADE: Close all ===
            elif current_time >= dtime(11, 0):
                if self.active_trades:
                    self.close_all()
                
                # Sleep until next day
                if current_time >= dtime(16, 0):
                    tomorrow = now + timedelta(days=1)
                    next_start = tomorrow.replace(hour=4, minute=0, second=0)
                    sleep_secs = (next_start - now).total_seconds()
                    logger.info(f"Sleeping until {next_start}")
                    time.sleep(sleep_secs)
            
            time.sleep(30)  # Check every 30 seconds


if __name__ == '__main__':
    trader = LiveTrader()
    try:
        trader.run()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        trader.close_all()
