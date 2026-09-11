from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import main
import state_store
from alpaca_trader import AlpacaTrader
from backtest import ReplayFeed, replay
from config import config
from institutional_strategy import InstitutionalStrategy, Position, Signal, SignalDirection
from models import OrderSide
from risk_policy import position_size, reset_session
from state_store import BotState, new_position
from trading_runtime import TradingRuntime


@pytest.fixture(autouse=True)
def isolate_state(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, 'STATE_PATH', str(tmp_path / 'state.json'))


def record(side='long'):
    return new_position('SPY', side, 100, 10, 98 if side == 'long' else 102,
                        104 if side == 'long' else 96)


def broker_position(side='long', qty=10):
    return {'symbol': 'SPY', 'side': side, 'entry_price': 100, 'qty': qty}


def order(oid='entry', status='filled', qty=10, price=100, legs=None):
    return {'id': oid, 'status': status, 'filled_qty': qty, 'filled_avg_price': price,
            'legs': legs or [], 'symbol': 'SPY', 'side': 'sell', 'qty': 10}


@pytest.fixture
def runtime():
    trader = Mock()
    trader.get_positions.return_value = []
    trader.open_orders.return_value = []
    trader.get_order_by_client_id.return_value = None
    trader.is_market_open.return_value = True
    trader.get_account.return_value = {'equity': 20000, 'buying_power': 20000}
    feed = Mock()
    feed.get_latest_price.return_value = 100
    feed.get_atr.return_value = 1
    strategy = InstitutionalStrategy(feed)
    strategy.is_execution_window = Mock(return_value=True)
    strategy.generate_all_signals = Mock(return_value=[])
    system = SimpleNamespace(state=BotState(), trader=trader, data_feed=feed, strategy=strategy)
    return TradingRuntime(system, on_closed=Mock())


def signal(side=SignalDirection.LONG, symbol='SPY'):
    return Signal(symbol, side, 100, 98 if side == SignalDirection.LONG else 102,
                  104 if side == SignalDirection.LONG else 96, 5, 101, -2, .2, 2)


def test_state_roundtrip_and_remove_last_position():
    state = BotState(session_date='2026-09-11')
    p = record()
    p.entry_order_id = 'order-1'
    state.add_position(p)
    state_store.save_state(state)
    loaded = state_store.load_state()
    assert loaded.to_dict() == state.to_dict()
    loaded.remove_position(p.position_id)
    assert loaded.positions == {}


@pytest.mark.parametrize('entry,stop,equity,power,expected', [
    (10, 9, 20000, 20000, 50), (100, 98, 20000, 20000, 20),
    (100, 99, 20000, 50, 0), (100, 40, 20000, 20000, 0),
    (100, 100, 20000, 20000, 0), (10, 10.3, 20000, 20000, 166),
])
def test_fifty_dollar_planned_risk(entry, stop, equity, power, expected):
    qty = position_size(entry, stop, equity, power)
    assert qty == expected
    assert qty * abs(entry - stop) <= 50 + 1e-9


def test_session_rollover_keeps_positions_and_resets_once():
    state = BotState(session_date='2026-09-10', trades_today=3, daily_pnl=-200,
                     consecutive_losses=3, portfolio_peak=22000)
    state.add_position(record())
    assert reset_session(state, datetime(2026, 9, 11, 9, 30))
    assert (state.trades_today, state.daily_pnl, state.consecutive_losses) == (0, 0, 0)
    assert state.portfolio_peak == 22000 and len(state.all_positions()) == 1
    state.trades_today = 1
    assert not reset_session(state, datetime(2026, 9, 11, 14))
    assert state.trades_today == 1


@pytest.mark.parametrize('direction,expected', [(SignalDirection.LONG, OrderSide.BUY),
                                              (SignalDirection.SHORT, OrderSide.SELL)])
def test_entry_direction_and_intent_saved_before_submit(runtime, direction, expected):
    def submit(*args, **kwargs):
        saved = state_store.load_state()
        assert saved.all_positions()[0].entry_client_id == kwargs['client_order_id']
        assert args[2] == expected
        return {'id': 'entry'}
    runtime.system.trader.submit_bracket_order.side_effect = submit
    runtime.submit_entry(signal(direction), 20000, 20000)
    assert runtime.state.trades_today == 1
    assert not runtime.state.all_positions()[0].entry_confirmed


@pytest.mark.parametrize('side', [OrderSide.BUY, OrderSide.SELL])
def test_actual_adapter_request_side(side):
    trader = AlpacaTrader()
    trader._initialized = True
    trader.trading_client = Mock()
    trader.trading_client.submit_order.return_value = SimpleNamespace(
        id='abc', symbol='SPY', side=side, qty='10', type=SimpleNamespace(value='market'),
        status=SimpleNamespace(value='accepted'), submitted_at=None)
    assert trader.submit_bracket_order('SPY', 10, side, 98, 104)
    request = trader.trading_client.submit_order.call_args.args[0]
    assert request.side.value == side.value
    assert request.time_in_force.value == 'gtc'


def test_recovery_preserves_stops_trailing_and_does_not_duplicate(runtime):
    p = record('short')
    p.trailing_stop = 99.5
    p.breakeven_active = True
    runtime.state.add_position(p)
    runtime.system.trader.get_positions.return_value = [broker_position('short')]
    runtime.reconcile()
    runtime.reconcile()
    assert runtime.ready
    assert len(runtime.state.all_positions()) == 1
    active = runtime.system.strategy.positions['SPY']
    assert active.stop == 102 and active.target == 96
    assert active.trailing_stop == 99.5 and active.initial_risk == 2


def test_unknown_short_adoption_has_correct_stop_direction(runtime):
    runtime.system.trader.get_positions.return_value = [broker_position('short')]
    runtime.reconcile()
    p = runtime.state.all_positions()[0]
    assert p.stop_price > p.entry_price > p.target_price


@pytest.mark.parametrize('condition', ['window', 'trades', 'loss', 'streak', 'drawdown'])
def test_exit_management_survives_entry_gates(runtime, condition):
    runtime.state.session_date = '2026-09-11'
    p = record()
    runtime.state.add_position(p)
    runtime.system.trader.get_positions.return_value = [broker_position()]
    runtime.system.data_feed.get_latest_price.return_value = 97
    runtime.system.trader.submit_market_order.return_value = {'id': 'close'}
    if condition == 'window':
        runtime.system.strategy.is_execution_window.return_value = False
    elif condition == 'trades':
        runtime.state.trades_today = 3
    elif condition == 'loss':
        runtime.state.daily_pnl = -200
    elif condition == 'streak':
        runtime.state.consecutive_losses = 3
    else:
        runtime.system.trader.get_account.return_value['equity'] = 18000
    runtime.tick(datetime(2026, 9, 11, 12))
    runtime.system.trader.submit_market_order.assert_called_once()
    runtime.system.strategy.generate_all_signals.assert_not_called()
    assert runtime.state.get_position(p.position_id) is p


def test_failed_close_preserves_position_and_pnl(runtime):
    p = record()
    p.entry_confirmed = True
    runtime.state.add_position(p)
    runtime.system.trader.get_positions.return_value = [broker_position()]
    runtime.system.trader.submit_market_order.return_value = None
    runtime.request_close(p, 'stop')
    runtime.request_close(p, 'stop')
    runtime.system.trader.submit_market_order.assert_called_once()
    assert runtime.state.daily_pnl == 0 and p.shares_remaining == 10
    assert p.exit_client_id is not None


def test_partial_exit_is_accounted_once_and_retained_until_filled(runtime):
    p = record()
    p.entry_order_id = 'entry'
    p.exit_order_ids = ['exit']
    runtime.state.add_position(p)
    orders = {'entry': order(), 'exit': order('exit', 'partially_filled', 4, 98)}
    runtime.system.trader.get_order.side_effect = lambda oid: orders[oid]
    runtime.reconcile_record(p)
    runtime.reconcile_record(p)
    assert p.shares_remaining == 6 and runtime.state.daily_pnl == -8
    assert runtime.state.get_position(p.position_id) is p
    orders['exit'] = order('exit', 'filled', 10, 97)
    runtime.reconcile_record(p)
    assert runtime.state.daily_pnl == -30
    assert runtime.state.positions == {}
    runtime.on_closed.assert_called_once()


def test_bracket_exit_uses_actual_fill(runtime):
    p = record()
    p.entry_order_id = 'entry'
    runtime.state.add_position(p)
    runtime.system.trader.get_order.return_value = order(legs=[order('tp', price=104)])
    runtime.reconcile()
    assert runtime.state.daily_pnl == 40
    assert not runtime.state.positions


def test_broker_outage_does_not_erase_state(runtime):
    p = record()
    runtime.state.add_position(p)
    runtime.system.trader.get_positions.side_effect = RuntimeError('offline')
    runtime.reconcile()
    assert not runtime.ready and runtime.state.get_position(p.position_id)


def test_wait_for_cancel_before_close(runtime):
    p = record()
    runtime.state.add_position(p)
    runtime.system.trader.open_orders.return_value = [{'id': 'stop'}]
    runtime.request_close(p, 'trailing_stop')
    runtime.system.trader.cancel_symbol_orders.assert_called_once_with('SPY')
    runtime.system.trader.submit_market_order.assert_not_called()


def test_daily_slots_enforced_within_signal_batch(runtime):
    runtime.state.session_date = '2026-09-11'
    runtime.state.trades_today = 2
    runtime.system.strategy.generate_all_signals.return_value = [signal(symbol=s) for s in ['SPY','QQQ','WMT']]
    runtime.system.trader.submit_bracket_order.return_value = {'id': 'entry'}
    runtime.tick(datetime(2026, 9, 11, 10))
    assert runtime.state.trades_today == 3
    runtime.system.trader.submit_bracket_order.assert_called_once()


def test_auth_missing_and_case_sensitive(monkeypatch):
    client = TestClient(main.app)
    monkeypatch.delenv('ADMIN_API_KEY', raising=False)
    assert client.post('/api/stop', headers={'Authorization': 'Bearer anything'}).status_code == 503
    monkeypatch.setenv('ADMIN_API_KEY', 'CaseSensitive')
    assert client.post('/api/stop', headers={'Authorization': 'Bearer casesensitive'}).status_code == 401
    assert client.post('/api/stop', headers={'Authorization': 'Bearer CaseSensitive'}).status_code == 200
    assert client.post('/api/stop').status_code in (401, 403)


def test_breakeven_only_after_one_r():
    p = Position('SPY', SignalDirection.LONG, 100, 10, 98, 104)
    p.update_trailing_stop(101, 1)
    assert not p.breakeven_active
    p.update_trailing_stop(102, 1)
    assert p.breakeven_active and p.trailing_stop == 100


def bars():
    index = pd.date_range('2026-09-11 09:30', periods=40, freq='min')
    return pd.DataFrame({'Open':100., 'High':100.2, 'Low':99.8, 'Close':100., 'Volume':1000}, index=index)


def test_replay_never_exposes_future_bars():
    data = bars()
    feed = ReplayFeed(data)
    feed.now = data.index[10]
    visible = feed.get_bars_yfinance('SPY')
    assert len(visible) == 10 and visible.index[-1] == data.index[9]


def test_signal_has_two_r_target_and_no_directionless_trade():
    feed = Mock()
    feed.get_latest_price.return_value = 98
    feed.get_volume_ratio.return_value = 2
    feed.get_adx.return_value = 30
    feed.get_atr.return_value = 1
    strategy = InstitutionalStrategy(feed)
    strategy.calculate_vwap_bands = Mock(return_value={'vwap':100, 'upper':101, 'lower':99, 'std_dev':1})
    strategy.calculate_opening_range = Mock(return_value={'is_narrow':True, 'range_pct':.2})
    strategy.is_execution_window = Mock(return_value=True)
    result = strategy.generate_signal('SPY')
    assert result.target - result.price == pytest.approx(2 * (result.price - result.stop))
    feed.get_latest_price.return_value = 100
    assert strategy.generate_signal('SPY') is None


def test_backtest_calls_live_signal_generator(monkeypatch):
    calls = []
    def generate(self, symbol):
        calls.append(self.data_feed.now)
        return None
    monkeypatch.setattr(InstitutionalStrategy, 'generate_signal', generate)
    result = replay('SPY', bars())
    assert calls and result['strategy'] == 'InstitutionalStrategy'
    assert result['total_trades'] == 0


def test_old_fill_does_not_consume_today_loss_budget(runtime):
    runtime.state.session_date = '2026-09-11'
    p = record()
    p.entry_order_id = 'entry'
    runtime.state.add_position(p)
    exit_order = order('stop', price=98)
    exit_order['filled_at'] = '2026-09-10T18:00:00+00:00'
    runtime.system.trader.get_order.return_value = order(legs=[exit_order])
    runtime.reconcile_record(p)
    assert runtime.state.daily_pnl == 0
    assert p.realized_pnl == -20


def test_corrupt_state_fails_closed():
    from pathlib import Path
    Path(state_store.STATE_PATH).write_text('invalid json')
    with pytest.raises(RuntimeError, match='refusing to discard'):
        state_store.load_state()
