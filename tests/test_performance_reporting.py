from datetime import datetime

import pytest

import main


@pytest.fixture
def ledger(monkeypatch):
    rows = [
        {'status': 'closed', 'pnl': -50., 'timestamp': '2026-09-21T14:00:00Z',
         'entry_time_et': '2026-09-21 10:00:00 EDT', 'exit_time': '2026-09-21T14:30:00Z',
         'exit_time_et': '2026-09-21 10:30:00 EDT'},
        {'status': 'closed', 'pnl': 20., 'timestamp': '2026-09-21T14:10:00Z',
         'entry_time_et': '2026-09-21 10:10:00 EDT', 'exit_time': '2026-09-21T14:20:00Z',
         'exit_time_et': '2026-09-21 10:20:00 EDT'},
        {'status': 'open', 'pnl': 0., 'timestamp': '2026-09-23T14:00:00Z',
         'entry_time_et': '2026-09-23 10:00:00 EDT'},
    ]
    monkeypatch.setattr(main, 'get_csv_trade_records', lambda: rows)
    monkeypatch.setattr(main, 'get_et_now', lambda: datetime(2026, 9, 23, 11))
    monkeypatch.setattr(main, 'get_trade_summary', lambda: {
        'total_trades': 15, 'wins': 0, 'losses': 0, 'total_pnl': 0.})
    return rows


def test_lifetime_summary_uses_closed_ledger_even_on_inactive_day(ledger):
    summary = main.get_closed_positions()
    assert summary['total_closed'] == 2
    assert summary['total_pnl'] == -30.
    assert summary['win_rate'] == 50.
    assert summary['avg_win'] == 20.
    assert summary['avg_loss'] == -50.
    assert main.get_trades()['total_pnl'] == -30.


def test_daily_summary_is_zero_on_inactive_day(ledger):
    assert main.get_daily()['total_trades'] == 0
    assert main.get_daily()['total_pnl'] == 0.


def test_daily_summary_uses_exit_date_not_entry_date(ledger):
    ledger[0]['exit_time_et'] = '2026-09-23 10:30:00 EDT'
    assert main.get_daily()['total_trades'] == 1
    assert main.get_daily()['total_pnl'] == -50.


@pytest.mark.parametrize('reverse', [False, True])
def test_curve_follows_exit_order(ledger, reverse):
    if reverse:
        ledger.reverse()
    assert main.get_pnl_curve() == [
        {'time': '2026-09-21 10:20:00 EDT', 'pnl': 20.},
        {'time': '2026-09-21 10:30:00 EDT', 'pnl': -30.},
    ]


def test_closed_trade_log_uses_exit_time(ledger):
    closed = [row for row in main.get_trade_logs() if row['pnl'] == -50.][0]
    assert closed['time_et'] == '2026-09-21 10:30:00 EDT'
    assert closed['time'] == '2026-09-21T14:30:00Z'
