"""Broker reconciliation and execution, independent of HTTP endpoints.

Persist submission intent before sending an order. Never infer a fill from an
acknowledgement, a quote, or a failed positions request.
"""
import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from config import config
from institutional_strategy import SignalDirection
from models import OrderSide
from risk_policy import entries_allowed, position_size, reset_session
from state_store import new_position, save_state

logger = logging.getLogger(__name__)
TERMINAL = {'filled', 'canceled', 'expired', 'rejected'}


class TradingRuntime:
    def __init__(self, system, on_closed=None, on_opened=None):
        self.system = system
        self.on_closed = on_closed or (lambda record: None)
        self.on_opened = on_opened or (lambda record: None)
        self.ready = False
        self.close_requested = False
        self.error = None

    @property
    def state(self):
        return self.system.state

    def persist(self):
        save_state(self.state)

    def restore_strategy(self):
        strategy = self.system.strategy
        strategy.positions.clear()
        strategy.portfolio_peak = self.state.portfolio_peak
        for p in self.state.all_positions():
            if p.shares_remaining <= 0:
                continue
            strategy.add_position(p.symbol, SignalDirection(p.side), p.entry_price,
                                  p.shares_remaining, p.stop_price, p.target_price)
            active = strategy.positions[p.symbol]
            active.trailing_stop = p.trailing_stop
            active.highest_profit = p.highest_profit
            active.breakeven_active = p.breakeven_active

    def reconcile(self):
        """Reconcile tracked orders first, then adopt actual broker positions."""
        self.ready = False
        self.error = None
        try:
            for p in list(self.state.all_positions()):
                self.reconcile_record(p)
            broker_positions = self.system.trader.get_positions(strict=True)
            actual = {p['symbol']: p for p in broker_positions}
            tracked = {p.symbol: p for p in self.state.all_positions()}
            for symbol, broker in actual.items():
                if symbol in tracked:
                    record = tracked[symbol]
                    if record.entry_confirmed and (
                        abs(record.shares_remaining - abs(broker['qty'])) > 1e-6
                        or record.side != broker['side']
                    ):
                        raise RuntimeError(f'{symbol}: broker quantity/side differs; reconciliation required')
                    continue
                # Recovery of legacy/manual positions: preserve actual side/quantity.
                # These fallback levels are explicit; persisted levels always win.
                sign = 1 if broker['side'] == 'long' else -1
                entry = broker['entry_price']
                p = new_position(symbol, broker['side'], entry, abs(broker['qty']),
                                 round(entry * (1 - sign * .005), 2),
                                 round(entry * (1 + sign * .005 * config.rr_ratio), 2))
                p.entry_confirmed = True
                p.notes = 'Recovered broker position; fallback risk levels'
                self.state.add_position(p)
                self.persist()
            for p in self.state.all_positions():
                if p.entry_confirmed and p.symbol not in actual:
                    raise RuntimeError(f'{p.symbol}: broker is flat but exit fills are unresolved')
                if p.entry_client_id and not p.entry_order_id:
                    raise RuntimeError(f'{p.symbol}: submission outcome unknown; resolve client order ID')
            self.restore_strategy()
            self.persist()
            self.ready = True
        except Exception as exc:
            self.error = str(exc)
            logger.error('Reconciliation blocked new entries: %s', exc)
            self.restore_strategy()

    def reconcile_record(self, p):
        trader = self.system.trader
        parent = None
        if p.entry_order_id:
            parent = trader.get_order(p.entry_order_id)
        elif p.entry_client_id:
            parent = trader.get_order_by_client_id(p.entry_client_id)
            if parent:
                p.entry_order_id = parent['id']
        if parent:
            filled = parent['filled_qty']
            if filled > 0:
                p.entry_price = parent['filled_avg_price']
                p.shares = filled
                p.shares_remaining = max(0, filled - p.accounted_exit_qty)
                if parent['status'] not in TERMINAL:
                    p.exit_reason = 'partial_entry'
            p.entry_confirmed = parent['status'] in TERMINAL and filled > 0
            if parent['status'] in TERMINAL and filled == 0:
                self.state.remove_position(p.position_id)
                self.persist()
                return
            if p.entry_confirmed and not p.entry_reported:
                p.entry_reported = True
                self.persist()
                try:
                    self.on_opened(p)
                except Exception:
                    logger.exception('Entry reporting failed for %s', p.symbol)
        if p.exit_client_id:
            close_order = trader.get_order_by_client_id(p.exit_client_id)
            if close_order:
                if close_order['id'] not in p.exit_order_ids:
                    p.exit_order_ids.append(close_order['id'])
                if close_order['status'] in TERMINAL:
                    p.exit_client_id = None
            else:
                # A timeout/404 cannot prove that a previous submission was rejected.
                self.persist()
                raise RuntimeError(f'{p.symbol}: close submission unresolved')
        exits = {o['id']: o for o in (parent or {}).get('legs', [])}
        for order_id in p.exit_order_ids:
            exits[order_id] = trader.get_order(order_id)
        # Legacy recovery has no parent ID. Attach existing protective orders so
        # their later fills can still be reconciled by ID (without history paging).
        if not p.entry_order_id and not p.entry_client_id:
            side = 'sell' if p.side == 'long' else 'buy'
            for order in trader.open_orders(p.symbol):
                if order['side'] == side:
                    if order['id'] not in p.exit_order_ids:
                        p.exit_order_ids.append(order['id'])
                    exits[order['id']] = order
            p.entry_confirmed = True
        qty = sum(o['filled_qty'] for o in exits.values())
        value = sum(o['filled_qty'] * o['filled_avg_price'] for o in exits.values())
        if qty > p.shares + 1e-6:
            raise RuntimeError(f'{p.symbol}: exit fills exceed entry quantity')
        if qty > p.accounted_exit_qty:
            delta_qty = qty - p.accounted_exit_qty
            delta_value = value - p.accounted_exit_value
            pnl = (delta_value - p.entry_price * delta_qty) * (1 if p.side == 'long' else -1)
            for oid, order in exits.items():
                previous = p.accounted_fills.get(oid, {'qty': 0, 'value': 0})
                order_value = order['filled_qty'] * order['filled_avg_price']
                incremental = (order_value - previous['value'] - p.entry_price *
                               (order['filled_qty'] - previous['qty'])) * (1 if p.side == 'long' else -1)
                filled_at = order.get('filled_at')
                session = (datetime.fromisoformat(filled_at.replace('Z', '+00:00'))
                           .astimezone(ZoneInfo('America/New_York')).date().isoformat()
                           if filled_at else self.state.session_date)
                if session == self.state.session_date:
                    self.state.daily_pnl += incremental
                p.accounted_fills[oid] = {'qty': order['filled_qty'], 'value': order_value}
            p.realized_pnl += pnl
            p.accounted_exit_qty = qty
            p.accounted_exit_value = value
            p.shares_remaining = max(0, p.shares - qty)
        if p.entry_confirmed and qty >= p.shares and qty > 0:
            fill_dates = [o.get('filled_at') for o in exits.values() if o['filled_qty'] > 0]
            latest_fill = max((d for d in fill_dates if d), default=None)
            close_session = (datetime.fromisoformat(latest_fill.replace('Z', '+00:00'))
                             .astimezone(ZoneInfo('America/New_York')).date().isoformat()
                             if latest_fill else self.state.session_date)
            if close_session == self.state.session_date:
                self.state.consecutive_losses = self.state.consecutive_losses + 1 if p.realized_pnl < 0 else 0
            self.state.remove_position(p.position_id)
            self.system.strategy.close_position(p.symbol)
            self.persist()
            try:
                self.on_closed(p)
            except Exception:
                logger.exception('Closed trade reporting failed for %s', p.symbol)
        else:
            self.persist()

    def request_close(self, p, reason):
        """Cancel conflicting orders, confirm cancellation, submit one close."""
        p.exit_reason = reason
        self.persist()
        if p.exit_client_id:
            return
        trader = self.system.trader
        if trader.open_orders(p.symbol):
            trader.cancel_symbol_orders(p.symbol)
            return  # Cancellation is asynchronous; reconcile before next attempt.
        self.reconcile_record(p)
        if self.state.get_position(p.position_id) is None:
            return
        broker = next((b for b in trader.get_positions(strict=True) if b['symbol'] == p.symbol), None)
        if broker is None:
            raise RuntimeError(f'{p.symbol}: no broker position; waiting for confirmed exit fills')
        if broker['side'] != p.side or abs(abs(broker['qty']) - p.shares_remaining) > 1e-6:
            raise RuntimeError(f'{p.symbol}: close quantity mismatch')
        p.exit_client_id = 'pulse-exit-' + uuid.uuid4().hex
        self.persist()
        result = trader.submit_market_order(
            p.symbol, p.shares_remaining,
            OrderSide.SELL if p.side == 'long' else OrderSide.BUY,
            client_order_id=p.exit_client_id)
        if result:
            p.exit_order_ids.append(result['id'])
        self.persist()

    def manage_positions(self):
        for p in list(self.state.all_positions()):
            try:
                if p.exit_reason or self.close_requested:
                    self.request_close(p, p.exit_reason or 'manual_close')
                    continue
                if not p.entry_confirmed:
                    continue
                active = self.system.strategy.positions.get(p.symbol)
                if active is None:
                    continue
                price = self.system.data_feed.get_latest_price(p.symbol)
                if not price:
                    continue
                atr = self.system.data_feed.get_atr(p.symbol, config.atr_length) or price * .005
                active.update_trailing_stop(price, atr)
                p.trailing_stop = active.trailing_stop
                p.highest_profit = active.highest_profit
                p.breakeven_active = active.breakeven_active
                self.persist()
                should_exit, reason = active.should_exit(price)
                if should_exit:
                    self.request_close(p, reason)
            except Exception as exc:
                self.ready = False
                self.error = str(exc)
                logger.exception('Position management failed for %s', p.symbol)

    def submit_entry(self, signal, equity, buying_power):
        side = {SignalDirection.LONG: OrderSide.BUY, SignalDirection.SHORT: OrderSide.SELL}[signal.direction]
        qty = position_size(signal.price, signal.stop, equity, buying_power)
        if qty <= 0:
            return
        p = new_position(signal.symbol, signal.direction.value, signal.price, qty,
                         signal.stop, signal.target)
        p.entry_client_id = 'pulse-entry-' + uuid.uuid4().hex
        self.state.add_position(p)
        # Reserve a daily slot before the request, including uncertain outcomes.
        self.state.trades_today += 1
        self.persist()
        result = self.system.trader.submit_bracket_order(
            signal.symbol, qty, side, signal.stop, signal.target,
            client_order_id=p.entry_client_id)
        if result:
            p.entry_order_id = result['id']
        self.persist()
        self.restore_strategy()

    def tick(self, now, allow_entries=True, skip_symbol=lambda symbol: False):
        if reset_session(self.state, now):
            self.persist()
        self.reconcile()
        if not self.system.trader.is_market_open():
            return
        # Existing exposure is managed regardless of entry hours or risk limits.
        self.manage_positions()
        if not self.ready or not allow_entries or self.close_requested:
            return
        account = self.system.trader.get_account()
        if not account or account.get('trading_blocked'):
            return
        equity = account['equity']
        eligible = entries_allowed(self.state, self.system.strategy, equity)
        self.state.portfolio_peak = self.system.strategy.portfolio_peak
        self.persist()
        if not eligible:
            return
        buying_power = account['buying_power']
        for signal in self.system.strategy.generate_all_signals():
            if len(self.state.all_positions()) >= 3 or self.state.trades_today >= config.max_trades_per_day:
                break
            if signal.symbol in self.state.positions or skip_symbol(signal.symbol):
                continue
            if not self.system.strategy.check_sector_exposure(signal.symbol):
                continue
            if self.system.trader.open_orders(signal.symbol):
                continue
            self.submit_entry(signal, equity, buying_power)
            records = self.state.positions.get(signal.symbol, [])
            if records:
                buying_power = max(0, buying_power - records[0].shares * signal.price)
