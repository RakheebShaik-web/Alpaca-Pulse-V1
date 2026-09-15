from types import SimpleNamespace

from discord_notifier import DiscordNotifier
import csv_log
from trade_journal import present_entries


def test_trade_records_use_eastern_time_and_short_exit_reasons():
    records = present_entries([{
        "timestamp": "2026-09-14T14:30:00+00:00",
        "exit_time": "2026-09-14T15:45:00+00:00",
        "exit_reason": "stop_loss",
    }])
    assert records[0]["entry_time_et"] == "2026-09-14 10:30:00 EDT"
    assert records[0]["exit_time_et"] == "2026-09-14 11:45:00 EDT"
    assert records[0]["exit_reason_label"] == "SL"


def test_discord_trade_alert_leads_with_ticker_side_quantity():
    notifier = DiscordNotifier("")
    notifier.send = lambda content, embeds=None: setattr(
        notifier, "captured", SimpleNamespace(content=content, embeds=embeds)
    ) or True
    notifier.send_trade_alert({"symbol": "SPY", "side": "long", "quantity": 12,
                               "entry": 100, "stop": 98, "tp": 104})
    assert notifier.captured.content == "SPY LONG 12"
    assert notifier.captured.embeds[0]["title"] == "SPY LONG 12"


def test_discord_exit_alert_includes_reason():
    notifier = DiscordNotifier("")
    notifier.send = lambda content, embeds=None: setattr(
        notifier, "captured", SimpleNamespace(content=content, embeds=embeds)
    ) or True
    notifier.send_exit_alert({"symbol": "SPY", "side": "long", "quantity": 12,
                              "entry": 100, "exit_price": 98, "pnl": -24,
                              "exit_reason": "stop_loss"})
    assert notifier.captured.content == "SPY LONG 12 | EXIT SL"
    assert notifier.captured.embeds[0]["title"] == "SPY LONG 12 | EXIT SL"


def test_csv_ledger_updates_one_trade_row_and_keeps_eastern_times(tmp_path, monkeypatch):
    path = tmp_path / "trades.csv"
    monkeypatch.setattr(csv_log, "CSV_PATH", str(path))
    csv_log.log_trade("SPY", "long", 100, shares=12, stop_price=98,
                      target_price=104, status="open", notes="pos_id=abc")
    csv_log.update_trade("abc", 98, -24, "stop_loss")
    records = csv_log.get_trade_records()
    assert len(records) == 1
    assert records[0]["status"] == "closed"
    assert records[0]["exit_reason_label"] == "SL"
    assert records[0]["entry_time_et"].endswith(("EST", "EDT"))
    assert records[0]["exit_time_et"].endswith(("EST", "EDT"))
