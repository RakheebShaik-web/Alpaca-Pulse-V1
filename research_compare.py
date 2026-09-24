"""Offline, fixed-rule QQQ comparison. Never submits orders or changes live config."""
import argparse
import json
from pathlib import Path

import pandas as pd

from backtest import normalize_bars, replay
from config import config
from institutional_strategy import InstitutionalStrategy, Signal, SignalDirection


class TrendPullback(InstitutionalStrategy):
    def generate_signal(self, symbol):
        bars = self.data_feed.get_bars_yfinance(symbol)
        if len(bars) < 60 or not self.is_execution_window():
            return None
        close = bars.Close
        fast = close.ewm(span=20, adjust=False).mean()
        slow = close.ewm(span=50, adjust=False).mean()
        price = float(close.iloc[-1])
        long = (fast.iloc[-1] > slow.iloc[-1] and slow.iloc[-1] > slow.iloc[-6]
                and bars.Low.iloc[-2] <= fast.iloc[-2]
                and price > fast.iloc[-1] and price > close.iloc[-2])
        short = (fast.iloc[-1] < slow.iloc[-1] and slow.iloc[-1] < slow.iloc[-6]
                 and bars.High.iloc[-2] >= fast.iloc[-2]
                 and price < fast.iloc[-1] and price < close.iloc[-2])
        if not (long or short):
            return None
        atr = self.data_feed.get_atr(symbol, config.atr_length)
        if atr is None or not pd.notna(atr) or atr <= 0:
            return None
        direction = SignalDirection.LONG if long else SignalDirection.SHORT
        sign = 1 if long else -1
        price = round(price, 2)
        stop = round(price - sign * atr * config.atr_stop_multiplier, 2)
        target = round(price + sign * abs(price - stop) * config.rr_ratio, 2)
        return Signal(symbol, direction, price, stop, target, 1, 0, 0, 0, 0)


def compare(csv_path):
    bars = normalize_bars(pd.read_csv(csv_path, index_col=0))
    dates = sorted(set(bars.index.date))
    if len(dates) < 20:
        raise ValueError('At least 20 sessions required; prefer 6–12 months of minute bars')
    split = dates[int(len(dates) * .7)]
    reports = {}
    for cls in (InstitutionalStrategy, TrendPullback):
        result = replay('QQQ', bars, slippage_bps=2, strategy_class=cls)
        for label, held_out in [('development', False), ('holdout', True)]:
            trades = [t for t in result['trades']
                      if (pd.Timestamp(t['entry_time']).date() >= split) == held_out]
            wins = sum(t['pnl'] > 0 for t in trades)
            profits = sum(max(0, t['pnl']) for t in trades)
            losses = -sum(min(0, t['pnl']) for t in trades)
            reports[f'{cls.__name__}/{label}'] = {
                'trades': len(trades), 'net_pnl': profits - losses,
                'win_rate': wins / len(trades) if trades else None,
                'expectancy': (profits - losses) / len(trades) if trades else None,
                'profit_factor': profits / losses if losses else None,
            }
    return {'holdout_start': str(split), 'results': reports,
            'warning': 'Hypothetical research, not actual performance. Open-only limit fills; '
                       '2 bps adverse execution; fee rate from config; no parameter search. '
                       'Insufficient trade counts do not establish an edge.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.csv), indent=2))
