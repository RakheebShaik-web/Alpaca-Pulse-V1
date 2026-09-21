from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd

from institutional_strategy import InstitutionalStrategy, Signal, SignalDirection
from state_store import BotState, new_position
from trading_runtime import TradingRuntime


def test_pending_position_blocks_second_submission():
    state = BotState()
    state.add_position(new_position('AAPL', 'long', 100, 10, 98, 104))
    trader = Mock()
    runtime = TradingRuntime(SimpleNamespace(state=state, trader=trader,
                                             strategy=InstitutionalStrategy(Mock())))
    signal = Signal('NVDA', SignalDirection.LONG, 100, 98, 104, 5, 100, 0, 0, 1)
    runtime.submit_entry(signal, 20000, 20000)
    trader.submit_bracket_order.assert_not_called()
    assert runtime.last_decisions[-1]['reason'] == 'position_or_pending_entry_exists'


def test_freshness_boundaries_and_invalid_prices():
    feed = Mock()
    strategy = InstitutionalStrategy(feed, clock=lambda: datetime(2026, 9, 22, 10, 0))
    bars = pd.DataFrame({'Open': [100.], 'High': [101.], 'Low': [99.],
                         'Close': [100.], 'Volume': [1000.]},
                        index=pd.DatetimeIndex(['2026-09-22 09:57']))
    feed.get_bars_yfinance.return_value = bars
    assert strategy.fresh_bars('QQQ')
    bars.index = pd.DatetimeIndex(['2026-09-22 09:56'])
    assert not strategy.fresh_bars('QQQ')
    bars.index = pd.DatetimeIndex(['2026-09-22 10:00'])
    assert not strategy.fresh_bars('QQQ')
    bars.index = pd.DatetimeIndex(['2026-09-22 09:59'])
    bars['Close'] = float('nan')
    assert not strategy.fresh_bars('QQQ')


def test_scan_records_stale_data_rejections():
    strategy = InstitutionalStrategy(Mock())
    strategy.fresh_bars = Mock(return_value=False)
    strategy.generate_signal = Mock()
    assert strategy.generate_all_signals() == []
    strategy.generate_signal.assert_not_called()
    assert strategy.scan_decisions
    assert all(row['reason'] == 'stale_or_invalid_data' for row in strategy.scan_decisions)
