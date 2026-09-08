#!/usr/bin/env python3
"""
Backtest: Pre-Market Momentum + Opening Range Breakout strategy.
Uses Yahoo Finance data (free, no API key needed).
Sends results to Discord.
"""

import sys
import time
import logging
from datetime import datetime, timedelta, time as dtime
from typing import Optional, Dict, List

import yfinance as yf
import pandas as pd
import numpy as np
import backtrader as bt

from config import config
from discord_notifier import DiscordNotifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Yahoo Finance data fetcher
# ──────────────────────────────────────────────────────────────────────

def fetch_yahoo_data(symbol: str, days: int = 180) -> pd.DataFrame:
    """
    Fetch intraday data from Yahoo Finance.
    
    Yahoo limits 5m data to 60 days, so we fetch in chunks for longer periods.
    """
    # Choose timeframe based on how much history we need
    if days <= 7:
        interval = "1m"
        chunk_size = 7
    elif days <= 60:
        interval = "5m"
        chunk_size = 60
    else:
        interval = "5m"
        chunk_size = 55  # Slightly less than 60 for safety
    
    logger.info(f"Downloading {symbol} ({interval}, {days} days)...")
    
    all_dfs = []
    end = datetime.now()
    
    # Fetch in chunks from oldest to newest
    remaining = days
    chunk_end = end
    while remaining > 0:
        chunk_start = chunk_end - timedelta(days=min(chunk_size, remaining))
        
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(
                start=chunk_start.strftime("%Y-%m-%d"),
                end=chunk_end.strftime("%Y-%m-%d"),
                interval=interval,
                prepost=True,
                repair=True,
            )
            if not df.empty:
                all_dfs.append(df)
                logger.info(f"  Chunk: {chunk_start.date()} to {chunk_end.date()} → {len(df)} bars")
        except Exception as e:
            logger.warning(f"  Chunk error {chunk_start.date()}: {e}")
        
        chunk_end = chunk_start
        remaining -= chunk_size
        # Rate limiting
        time.sleep(0.5)
    
    if not all_dfs:
        logger.warning(f"No data returned for {symbol}")
        return pd.DataFrame()
    
    # Combine and deduplicate
    combined = pd.concat(all_dfs)
    combined = combined[~combined.index.duplicated(keep='last')]
    
    # Normalize index
    combined.index = combined.index.tz_localize(None) if combined.index.tz else combined.index
    combined = combined.sort_index()
    
    # Filter to market hours (4:00 AM - 4:00 PM ET)
    combined = combined[(combined.index.hour >= 4) & (combined.index.hour < 16)]
    
    logger.info(f"Got {len(combined)} bars from {combined.index[0]} to {combined.index[-1]}")
    return combined


# ──────────────────────────────────────────────────────────────────────
# Custom VWAP indicator (backtrader doesn't include one)
# ──────────────────────────────────────────────────────────────────────

class VWAP(bt.Indicator):
    """Volume-Weighted Average Price, resets daily."""
    lines = ('vwap',)
    plotinfo = dict(subplot=False)
    
    def __init__(self):
        self.cum_vp = 0.0
        self.cum_vol = 0.0
        self.last_date = None
    
    def next(self):
        dt = self.datas[0].datetime.date(0)
        
        # Reset at start of each new day
        if dt != self.last_date:
            self.cum_vp = 0.0
            self.cum_vol = 0.0
            self.last_date = dt
        
        high = self.data.high[0]
        low = self.data.low[0]
        close = self.data.close[0]
        volume = self.data.volume[0]
        
        typical_price = (high + low + close) / 3
        self.cum_vp += typical_price * volume
        self.cum_vol += volume
        
        if self.cum_vol > 0:
            self.lines.vwap[0] = self.cum_vp / self.cum_vol
        else:
            self.lines.vwap[0] = close


# ──────────────────────────────────────────────────────────────────────
# Strategy
# ──────────────────────────────────────────────────────────────────────

class MomentumORB(bt.Strategy):
    """
    Pre-Market Momentum + Opening Range Breakout.
    
    1. Track pre-market high/low/volume (4:00-9:30 AM)
    2. Build opening range (9:30-9:45 AM)
    3. Trade breakouts with VWAP confirmation
    4. Fixed $50 stop, 1.5:1 target
    """
    
    params = (
        ('risk_per_trade', 50),
        ('max_trades', 3),
        ('max_daily_loss', 100),
        ('target_daily_pnl', 150),
        ('rr_ratio', 1.5),
        ('gap_threshold', 0.003),    # 0.3% gap (realistic for liquid stocks)
        ('or_minutes', 15),
        ('notifier', None),
    )
    
    def __init__(self):
        self.ema9 = bt.indicators.EMA(period=9)
        self.atr = bt.indicators.ATR(period=14)
        
        # Custom VWAP (backtrader doesn't have built-in VWAP)
        self.vwap = VWAP()
        
        # State
        self.or_high = None
        self.or_low = None
        self.pm_high = None
        self.pm_low = None
        self.pm_open = None
        self.prev_close = None
        self.daily_prev_close = None  # Track previous day's close properly
        
        self.trades_today = 0
        self.daily_pnl = 0.0
        self.current_date = None
        self.order = None
        
        # Tracking
        self.all_trades: List[Dict] = []
        self.daily_summaries: List[Dict] = []
        self.debug = False
        
        # Active trade tracking (manual stop/target management)
        self.active_entry = None
        self.active_stop = None
        self.active_tp = None
        self.active_side = None  # 'long' or 'short'
        self.active_size = 0
    
    def log(self, txt: str):
        dt = self.datas[0].datetime.datetime(0)
        print(f'{dt.strftime("%Y-%m-%d %H:%M")} | {txt}')
    
    def notify_order(self, order):
        if order.status in [order.Completed]:
            side = 'BUY' if order.isbuy() else 'SELL'
            self.log(f'{side} FILL: ${order.executed.price:.2f} x{order.executed.size}')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'ORDER FAILED: {order.status}')
        self.order = None
    
    def notify_trade(self, trade):
        if trade.isclosed:
            self.daily_pnl += trade.pnlcomm
            self.log(f'TRADE CLOSED: ${trade.pnlcomm:+.2f} | Daily: ${self.daily_pnl:+.2f}')
            
            # Track trade
            self.all_trades.append({
                'symbol': trade.data._name,
                'entry': trade.price,
                'exit': trade.barclose,
                'pnl': trade.pnlcomm,
                'bars': trade.barlen,
            })
            
            # Discord alert
            if self.p.notifier:
                self.p.notifier.send_exit_alert({
                    'symbol': trade.data._name,
                    'direction': 'LONG' if trade.size > 0 else 'SHORT',
                    'entry': trade.price,
                    'exit_price': trade.barclose,
                    'pnl': trade.pnlcomm,
                    'daily_pnl': self.daily_pnl,
                })
    
    def next(self):
        dt = self.datas[0].datetime.datetime(0)
        current_date = dt.date()
        current_time = dt.time()
        
        # Reset daily state
        if current_date != self.current_date:
            # End of previous day summary
            if self.current_date is not None:
                wins = sum(1 for t in self.all_trades if t['pnl'] > 0)
                total = len(self.all_trades)
                summary = {
                    'date': str(self.current_date),
                    'trades': self.trades_today,
                    'win_rate': wins / total if total > 0 else 0,
                    'daily_pnl': self.daily_pnl,
                    'portfolio': self.broker.getvalue(),
                }
                self.daily_summaries.append(summary)
                
                if self.p.notifier:
                    self.p.notifier.send_daily_summary(summary)
            
            self.current_date = current_date
            self.trades_today = 0
            self.daily_pnl = 0.0
            self.or_high = None
            self.or_low = None
            self.pm_high = None
            self.pm_low = None
            self.pm_open = None
            # prev_close is set from the last known close (previous day's close)
            self.prev_close = self.daily_prev_close
            self.log(f'--- NEW DAY | Prev Close: {self.prev_close} ---')
        
        # At end of day, save close for next day's gap calculation
        self.daily_prev_close = self.data.close[0]
        
        if self.order:
            return
        
        # Daily limits
        if self.trades_today >= self.p.max_trades:
            return
        if self.daily_pnl <= -self.p.max_daily_loss:
            return
        if self.daily_pnl >= self.p.target_daily_pnl:
            return
        
        # === PRE-MARKET: Track range ===
        if dtime(4, 0) <= current_time < dtime(9, 30):
            if self.pm_high is None:
                self.pm_high = self.data.high[0]
                self.pm_low = self.data.low[0]
                self.pm_open = self.data.open[0]
                if self.debug:
                    self.log(f'PM OPEN: {self.pm_open} | Prev Close: {self.prev_close}')
            else:
                self.pm_high = max(self.pm_high, self.data.high[0])
                self.pm_low = min(self.pm_low, self.data.low[0])
            return
        
        # === OPENING RANGE: Build OR ===
        if dtime(9, 30) <= current_time < dtime(9, 45):
            if self.or_high is None:
                self.or_high = self.data.high[0]
                self.or_low = self.data.low[0]
            else:
                self.or_high = max(self.or_high, self.data.high[0])
                self.or_low = min(self.or_low, self.data.low[0])
            return
        
        # === MANAGE ACTIVE TRADES ===
        if self.active_entry is not None:
            high = self.data.high[0]
            low = self.data.low[0]
            close = self.data.close[0]
            
            if self.active_side == 'long':
                # Check stop loss
                if low <= self.active_stop:
                    self.order = self.close()
                    pnl = (self.active_stop - self.active_entry) * self.active_size
                    self.daily_pnl += pnl
                    self.log(f'STOP HIT: ${self.active_stop:.2f} | PnL: ${pnl:+.2f}')
                    self.all_trades.append({'pnl': pnl})
                    self._reset_active()
                    self.order = None  # Allow next trade
                # Check take profit
                elif high >= self.active_tp:
                    self.order = self.close()
                    pnl = (self.active_tp - self.active_entry) * self.active_size
                    self.daily_pnl += pnl
                    self.log(f'TARGET HIT: ${self.active_tp:.2f} | PnL: ${pnl:+.2f}')
                    self.all_trades.append({'pnl': pnl})
                    self._reset_active()
                    self.order = None
                # Time exit at 10:50 AM
                elif current_time.hour == 10 and current_time.minute >= 50:
                    self.order = self.close()
                    pnl = (close - self.active_entry) * self.active_size
                    self.daily_pnl += pnl
                    self.log(f'TIME EXIT: ${close:.2f} | PnL: ${pnl:+.2f}')
                    self.all_trades.append({'pnl': pnl})
                    self._reset_active()
            
            elif self.active_side == 'short':
                # Check stop loss
                if high >= self.active_stop:
                    self.order = self.close()
                    pnl = (self.active_entry - self.active_stop) * self.active_size
                    self.daily_pnl += pnl
                    self.log(f'STOP HIT: ${self.active_stop:.2f} | PnL: ${pnl:+.2f}')
                    self.all_trades.append({'pnl': pnl})
                    self._reset_active()
                    self.order = None
                # Check take profit
                elif low <= self.active_tp:
                    self.order = self.close()
                    pnl = (self.active_entry - self.active_tp) * self.active_size
                    self.daily_pnl += pnl
                    self.log(f'TARGET HIT: ${self.active_tp:.2f} | PnL: ${pnl:+.2f}')
                    self.all_trades.append({'pnl': pnl})
                    self._reset_active()
                    self.order = None
                # Time exit at 10:50 AM
                elif current_time.hour == 10 and current_time.minute >= 50:
                    self.order = self.close()
                    pnl = (self.active_entry - close) * self.active_size
                    self.daily_pnl += pnl
                    self.log(f'TIME EXIT: ${close:.2f} | PnL: ${pnl:+.2f}')
                    self.all_trades.append({'pnl': pnl})
                    self._reset_active()
            
            return
        
        # === TRADING HOURS: Execute ===
        if dtime(9, 45) <= current_time < dtime(11, 0):
            if self.active_entry is None and self.or_high is not None:
                price = self.data.close[0]
                
                # Calculate gap
                gap_pct = 0
                if self.prev_close and self.prev_close > 0 and self.pm_open:
                    gap_pct = (self.pm_open - self.prev_close) / self.prev_close
                
                # Debug: log conditions every 15 minutes
                if current_time.minute == 0 and self.debug:
                    self.log(f'CHECK: Price={price:.2f} OR_H={self.or_high:.2f} OR_L={self.or_low:.2f} '
                            f'VWAP={self.vwap[0]:.2f} Gap={gap_pct:+.2%} EMA9={self.ema9[0]:.2f}')
                
                # LONG: Gap up + breakout above OR high + above VWAP
                if (gap_pct > self.p.gap_threshold and
                    price > self.or_high and
                    price > self.vwap[0]):
                    
                    stop = self.or_low
                    risk = price - stop
                    if risk > 0:
                        size = max(1, int(self.p.risk_per_trade / risk))
                        tp = price + (risk * self.p.rr_ratio)
                        
                        self.order = self.buy(size=size)
                        self.trades_today += 1
                        self.active_entry = price
                        self.active_stop = stop
                        self.active_tp = tp
                        self.active_side = 'long'
                        self.active_size = size
                        self.log(f'LONG: ${price:.2f} | Stop: ${stop:.2f} | '
                                f'TP: ${tp:.2f} | Size: {size} | Gap: {gap_pct:+.2%}')
                        
                        # Discord alert
                        if self.p.notifier:
                            self.p.notifier.send_trade_alert({
                                'symbol': self.data._name,
                                'direction': 'LONG',
                                'entry': price,
                                'stop': stop,
                                'tp': tp,
                                'size': size,
                                'risk': risk * size,
                                'gap_pct': gap_pct,
                            })
                
                # SHORT: Gap down + breakout below OR low + below VWAP
                elif (gap_pct < -self.p.gap_threshold and
                      price < self.or_low and
                      price < self.vwap[0]):
                    
                    stop = self.or_high
                    risk = stop - price
                    if risk > 0:
                        size = max(1, int(self.p.risk_per_trade / risk))
                        tp = price - (risk * self.p.rr_ratio)
                        
                        self.order = self.sell(size=size)
                        self.trades_today += 1
                        self.active_entry = price
                        self.active_stop = stop
                        self.active_tp = tp
                        self.active_side = 'short'
                        self.active_size = size
                        self.log(f'SHORT: ${price:.2f} | Stop: ${stop:.2f} | '
                                f'TP: ${tp:.2f} | Size: {size} | Gap: {gap_pct:+.2%}')
                        
                        # Discord alert
                        if self.p.notifier:
                            self.p.notifier.send_trade_alert({
                                'symbol': self.data._name,
                                'direction': 'SHORT',
                                'entry': price,
                                'stop': stop,
                                'tp': tp,
                                'size': size,
                                'risk': risk * size,
                                'gap_pct': gap_pct,
                            })
                
                # MOMENTUM BURST: No gap required, just OR breakout + volume
                elif (price > self.or_high * 1.002 and  # 0.2% above OR high
                      price > self.vwap[0] and
                      self.data.volume[0] > self.data.volume[-1] * 1.5):  # Volume surge
                    
                    stop = self.or_low
                    risk = price - stop
                    if risk > 0:
                        size = max(1, int(self.p.risk_per_trade / risk))
                        tp = price + (risk * self.p.rr_ratio)
                        
                        self.order = self.buy(size=size)
                        self.trades_today += 1
                        self.active_entry = price
                        self.active_stop = stop
                        self.active_tp = tp
                        self.active_side = 'long'
                        self.active_size = size
                        self.log(f'MOMENTUM LONG: ${price:.2f} | Stop: ${stop:.2f} | '
                                f'TP: ${tp:.2f} | Size: {size} | Vol: {self.data.volume[0]:.0f}')
                        
                        if self.p.notifier:
                            self.p.notifier.send_trade_alert({
                                'symbol': self.data._name,
                                'direction': 'LONG',
                                'entry': price,
                                'stop': stop,
                                'tp': tp,
                                'size': size,
                                'risk': risk * size,
                                'gap_pct': gap_pct,
                            })
    
    def _reset_active(self):
        """Reset active trade tracking."""
        self.active_entry = None
        self.active_stop = None
        self.active_tp = None
        self.active_side = None
        self.active_size = 0
    
    def stop(self):
        print('\n' + '=' * 60)
        print('BACKTEST COMPLETE')
        print('=' * 60)


# ──────────────────────────────────────────────────────────────────────
# Run backtest
# ──────────────────────────────────────────────────────────────────────

def run_backtest(symbol: str = 'SPY', days: int = 60, 
                 discord_webhook: Optional[str] = None):
    """Run backtest on a single symbol."""
    
    # Discord notifier
    notifier = DiscordNotifier(discord_webhook or "")
    
    print(f'\n{"=" * 60}')
    print(f'BACKTEST: {symbol} | {days} days | ${config.capital:,.0f} capital')
    print(f'{"=" * 60}\n')
    
    # Fetch data
    df = fetch_yahoo_data(symbol, days)
    if df.empty:
        print("No data fetched. Check symbol and connectivity.")
        return None
    
    # Run backtest
    cerebro = bt.Cerebro()
    cerebro.addstrategy(MomentumORB, notifier=notifier)
    
    data = bt.feeds.PandasData(dataname=df, name=symbol)
    cerebro.adddata(data)
    
    cerebro.broker.setcash(config.capital)
    cerebro.broker.setcommission(commission=config.commission)
    
    # Analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.02)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    
    results = cerebro.run()
    strat = results[0]
    
    # Report
    final_value = cerebro.broker.getvalue()
    total_return = ((final_value / config.capital) - 1) * 100
    
    print(f'\n{"=" * 60}')
    print('RESULTS')
    print(f'{"=" * 60}')
    print(f'Final Value:      ${final_value:>12,.2f}')
    print(f'Total Return:     {total_return:>11.2f}%')
    
    report = {
        'symbol': symbol,
        'final_value': final_value,
        'total_return': total_return,
    }
    
    try:
        sharpe = strat.analyzers.sharpe.get_analysis()
        sharpe_ratio = sharpe.get("sharperatio", 0) or 0
        print(f'Sharpe Ratio:     {sharpe_ratio:>11.3f}')
        report['sharpe'] = sharpe_ratio
    except:
        pass
    
    try:
        dd = strat.analyzers.drawdown.get_analysis()
        max_dd = dd.max.drawdown
        print(f'Max Drawdown:     {max_dd:>11.2f}%')
        report['max_drawdown'] = max_dd
    except:
        pass
    
    try:
        trades = strat.analyzers.trades.get_analysis()
        total = trades.total.closed
        if total > 0:
            won = trades.won.total
            lost = trades.lost.total
            avg_win = trades.won.pnl.average
            avg_loss = trades.lost.pnl.average
            profit_factor = abs(trades.won.pnl.total / trades.lost.pnl.total) if trades.lost.pnl.total != 0 else float('inf')
            
            print(f'Total Trades:     {total:>11}')
            print(f'Win Rate:         {won/total*100:>11.1f}%')
            print(f'Avg Win:          ${avg_win:>11.2f}')
            print(f'Avg Loss:         ${avg_loss:>11.2f}')
            print(f'Profit Factor:    {profit_factor:>11.2f}')
            
            report.update({
                'total_trades': total,
                'win_rate': won/total,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'profit_factor': profit_factor,
            })
    except:
        pass
    
    # Send summary to Discord
    if notifier.enabled:
        summary_text = (
            f"**Backtest Complete: {symbol}**\n"
            f"Final Value: `${final_value:,.2f}` ({total_return:+.2f}%)\n"
            f"Trades: {report.get('total_trades', 0)} | "
            f"Win Rate: {report.get('win_rate', 0):.0%}\n"
            f"Profit Factor: {report.get('profit_factor', 0):.2f}"
        )
        notifier.send(summary_text)
    
    # Plot
    # cerebro.plot(style='candlestick', barup='green', bardown='red', volume=True)  # Disabled for speed
    
    return report


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'SPY'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    webhook = sys.argv[3] if len(sys.argv) > 3 else None
    run_backtest(symbol, days, webhook)
