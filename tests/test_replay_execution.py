import pandas as pd
import pytest

from backtest import ReplayFeed, replay
from institutional_strategy import InstitutionalStrategy, Signal, SignalDirection
from config import config


@pytest.fixture(autouse=True)
def enable_market_alignment(monkeypatch):
    monkeypatch.setattr(config, 'market_alignment_filter', True)


def frame():
    return pd.DataFrame({'Open': 100., 'High': 100.1, 'Low': 99.9,
                         'Close': 100., 'Volume': 1000.},
                        index=pd.date_range('2026-09-11 09:30', '2026-09-11 15:59', freq='min'))


def test_market_data_is_not_substituted():
    stock = frame()
    market = frame() * 2
    feed = ReplayFeed(stock, 'AAPL', market)
    feed.now = stock.index[3]
    assert feed.get_bars_yfinance('QQQ').Close.iloc[-1] == 200
    assert feed.get_bars_yfinance('AAPL').Close.iloc[-1] == 100
    assert feed.get_bars_yfinance('MSFT').empty
    with pytest.raises(ValueError, match='QQQ bars'):
        replay('AAPL', stock)


class Once(InstitutionalStrategy):
    def generate_signal(self, symbol):
        if self.clock().strftime('%H:%M') == '09:45':
            return Signal(symbol, SignalDirection.LONG, 100, 98, 104, 5, 100, 0, 0, 1)


def test_limit_waits_for_price_and_closes_at_cutoff():
    bars = frame()
    bars.loc['2026-09-11 09:45', ['Open', 'High', 'Low', 'Close']] = [101, 101.1, 100.9, 101]
    result = replay('QQQ', bars, slippage_bps=0, strategy_class=Once)
    assert len(result['trades']) == 1
    trade = result['trades'][0]
    assert trade['entry_time'] == '2026-09-11T09:46:00'
    assert trade['entry'] <= 100
    assert trade['exit_time'] == '2026-09-11T15:50:00'
    assert trade['reason'] == 'close_eod'
    assert result['open_positions'] == 0


def test_online_backtest_fetches_market_history(monkeypatch):
    import backtest
    requested = []

    def fetch(symbol, days):
        requested.append(symbol)
        return frame()

    monkeypatch.setattr(backtest, 'fetch_yahoo_data', fetch)
    backtest.run_backtest('AAPL')
    assert requested == ['AAPL', 'QQQ']


def test_csv_backtest_requires_matching_market_file(tmp_path):
    from backtest import run_backtest
    path = tmp_path / 'stock.csv'
    frame().to_csv(path)
    with pytest.raises(ValueError, match='--market-csv'):
        run_backtest('AAPL', csv_path=path)
    assert run_backtest('AAPL', csv_path=path, market_csv_path=path)['symbol'] == 'AAPL'


def test_pending_limit_expires_between_sessions():
    first = frame().loc[:'2026-09-11 09:45'].copy()
    first.loc['2026-09-11 09:45', ['Open', 'High', 'Low', 'Close']] = [101, 101.1, 100.9, 101]
    second = frame().iloc[:5].copy()
    second.index += pd.Timedelta(days=3)
    result = replay('QQQ', pd.concat([first, second]), slippage_bps=0, strategy_class=Once)
    assert result['open_positions'] == 0
    assert result['total_trades'] == 0
