"""Replay the live InstitutionalStrategy; minute bars, next-bar entries."""
import argparse
import json
import pandas as pd
import yfinance as yf
from config import config
from data_feed import DataFeed
from institutional_strategy import InstitutionalStrategy, SignalDirection
from risk_policy import entries_allowed, position_size, reset_session
from state_store import BotState


def normalize_bars(df):
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_convert('America/New_York').tz_localize(None)
    df = df.rename(columns={c: c.title() for c in df.columns})
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].sort_index()
    if df.index.has_duplicates or df.empty or df.isna().any().any():
        raise ValueError('Bars must be nonempty, unique and complete')
    return df


def fetch_yahoo_data(symbol, days=7):
    if not 1 <= days <= 7:
        raise ValueError('Supply a historical CSV for more than 7 days of minute data')
    return normalize_bars(yf.Ticker(symbol).history(period=f'{days}d', interval='1m', prepost=True))


class ReplayFeed(DataFeed):
    def __init__(self, bars):
        self.bars = bars
        self.now = bars.index[0]

    def get_bars_yfinance(self, symbol, days=5):
        start = self.now - pd.Timedelta(days=min(days + 3, 7))
        return self.bars.loc[(self.bars.index >= start) &
                             (self.bars.index + pd.Timedelta(minutes=1) <= self.now)]

    def get_latest_price(self, symbol):
        bars = self.get_bars_yfinance(symbol)
        return float(bars['Close'].iloc[-1]) if len(bars) else None


def replay(symbol, bars, slippage_bps=1.0):
    if slippage_bps < 0:
        raise ValueError('Slippage must be nonnegative')
    bars = normalize_bars(bars)
    feed = ReplayFeed(bars)
    strategy = InstitutionalStrategy(feed, clock=lambda: feed.now.to_pydatetime())
    strategy.portfolio_peak = config.capital
    state = BotState(balance=config.capital)
    pending = None
    trades = []
    peak, max_dd, equity = config.capital, 0.0, config.capital

    def close(position, price, reason):
        sign = 1 if position.direction == SignalDirection.LONG else -1
        fill = price if reason == 'target' else price * (1 - sign * slippage_bps / 10000)
        pnl = sign * (fill - position.entry_price) * position.shares
        pnl -= (fill + position.entry_price) * position.shares * config.commission
        state.balance += pnl
        state.daily_pnl += pnl
        state.consecutive_losses = state.consecutive_losses + 1 if pnl < 0 else 0
        trades.append({'symbol': symbol, 'entry': position.entry_price, 'exit': fill,
                       'shares': position.shares, 'pnl': pnl, 'reason': reason,
                       'fill_risk': position.initial_risk * position.shares})
        strategy.close_position(symbol)

    for timestamp, bar in bars.iterrows():
        feed.now = timestamp
        reset_session(state, timestamp)
        if not pd.Timestamp('09:30').time() <= timestamp.time() < pd.Timestamp('16:00').time():
            pending = None
            continue
        if pending is not None:
            if entries_allowed(state, strategy, state.balance):
                sign = 1 if pending.direction == SignalDirection.LONG else -1
                fill = float(bar.Open) * (1 + sign * slippage_bps / 10000)
                valid = pending.stop < fill < pending.target if sign == 1 else pending.target < fill < pending.stop
                qty = position_size(pending.price, pending.stop, state.balance, state.balance)
                if valid and qty > 0:
                    strategy.add_position(symbol, pending.direction, fill, qty, pending.stop, pending.target)
                    state.trades_today += 1
            pending = None
        position = strategy.positions.get(symbol)
        if position:
            sign = 1 if position.direction == SignalDirection.LONG else -1
            stop = position.stop
            if position.trailing_stop is not None:
                stop = max(stop, position.trailing_stop) if sign == 1 else min(stop, position.trailing_stop)
            stop_hit = bar.Low <= stop if sign == 1 else bar.High >= stop
            target_hit = bar.High >= position.target if sign == 1 else bar.Low <= position.target
            # Intrabar ordering is unknown: assume the adverse stop fires first.
            if stop_hit:
                fill = min(float(bar.Open), stop) if sign == 1 else max(float(bar.Open), stop)
                close(position, fill, 'stop')
            elif target_hit:
                close(position, position.target, 'target')
            else:
                feed.now = timestamp + pd.Timedelta(minutes=1)
                atr = feed.get_atr(symbol, config.atr_length) or float(bar.Close) * .005
                position.update_trailing_stop(float(bar.Close), atr)
        feed.now = timestamp + pd.Timedelta(minutes=1)
        position = strategy.positions.get(symbol)
        unrealized = 0 if not position else (float(bar.Close) - position.entry_price) * position.shares * (1 if position.direction == SignalDirection.LONG else -1)
        equity = state.balance + unrealized
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100)
        if not position and entries_allowed(state, strategy, equity):
            pending = strategy.generate_signal(symbol)
    wins = [t['pnl'] for t in trades if t['pnl'] > 0]
    losses = [t['pnl'] for t in trades if t['pnl'] < 0]
    return {'strategy': 'InstitutionalStrategy', 'symbol': symbol, 'final_value': equity,
            'total_return': (equity / config.capital - 1) * 100, 'total_trades': len(trades),
            'win_rate': len(wins) / len(trades) if trades else 0,
            'profit_factor': sum(wins) / abs(sum(losses)) if losses else None,
            'max_drawdown': max_dd, 'open_positions': len(strategy.positions), 'trades': trades}


def run_backtest(symbol='SPY', days=7, discord_webhook=None, csv_path=None):
    if discord_webhook:
        raise ValueError('Backtests do not send external notifications')
    bars = pd.read_csv(csv_path, index_col=0) if csv_path else fetch_yahoo_data(symbol, days)
    report = replay(symbol, bars)
    print(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('symbol', nargs='?', default='SPY')
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--csv')
    args = parser.parse_args()
    run_backtest(args.symbol, args.days, csv_path=args.csv)
