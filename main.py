#!/usr/bin/env python3
"""FastAPI server and supervised trading runtime for Pulse V1."""
import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from alpaca_trader import AlpacaTrader
from csv_log import get_trade_records as get_csv_trade_records
from csv_log import get_trade_summary, log_trade, update_trade
from data_feed import DataFeed
from discord_notifier import DiscordNotifier
from earnings_filter import earnings_filter
from institutional_strategy import InstitutionalStrategy, get_et_now
from state_store import BotState, load_state, save_state
from trade_journal import journal
from trading_runtime import TradingRuntime

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)


def require_admin_key(credentials: HTTPAuthorizationCredentials | None = Depends(security),
                      x_admin_api_key: str = Header(default='')):
    admin_key = os.getenv('ADMIN_API_KEY')
    if not admin_key:
        raise HTTPException(status_code=503, detail='ADMIN_API_KEY is not configured')
    provided = credentials.credentials if credentials else x_admin_api_key
    if not secrets.compare_digest(provided, admin_key):
        raise HTTPException(status_code=401, detail='Invalid API key')
    return True


class TradingSystem:
    def __init__(self):
        self.trader = AlpacaTrader()
        self.data_feed = DataFeed(self.trader)
        self.strategy = InstitutionalStrategy(self.data_feed)
        self.notifier = DiscordNotifier(os.getenv('DISCORD_WEBHOOK_URL', ''))
        self.state = BotState()
        self.status = 'stopped'
        self.mode = 'paper'
        self.start_time = None
        self._trading_task = None

    def get_portfolio_value(self):
        try:
            account = self.trader.get_account()
            return account['equity'] if account else 0.0
        except Exception:
            return 0.0

    def get_buying_power(self):
        try:
            account = self.trader.get_account()
            return account['buying_power'] if account else 0.0
        except Exception:
            return 0.0


system = TradingSystem()


def report_closed(position):
    exit_price = position.accounted_exit_value / position.accounted_exit_qty
    reason = position.exit_reason or 'broker_exit'
    update_trade(position.position_id, exit_price, position.realized_pnl, reason)
    journal.close_entry(position.symbol, exit_price, reason,
                        position.trailing_stop is not None, position.breakeven_active)
    system.notifier.send_exit_alert({
        'symbol': position.symbol, 'side': position.side,
        'quantity': position.accounted_exit_qty, 'entry': position.entry_price,
        'exit_price': exit_price, 'pnl': position.realized_pnl,
        'daily_pnl': system.state.daily_pnl, 'exit_reason': reason,
    })


def report_opened(position):
    log_trade(symbol=position.symbol, side=position.side,
              entry_price=position.entry_price, shares=position.shares,
              stop_price=position.stop_price, target_price=position.target_price,
              status='open', notes=f'pos_id={position.position_id}')
    journal.add_entry(position.symbol, position.side, position.entry_price,
                      position.shares, position.stop_price, position.target_price,
                      0, 'InstitutionalStrategy; broker-confirmed fill', 'not recorded')
    system.notifier.send_trade_alert({
        'symbol': position.symbol, 'side': position.side,
        'quantity': position.shares, 'entry': position.entry_price,
        'stop': position.stop_price, 'tp': position.target_price,
        'risk': abs(position.entry_price - position.stop_price) * position.shares,
    })


runtime = TradingRuntime(system, on_closed=report_closed, on_opened=report_opened)


async def trading_loop():
    while True:
        try:
            if system.status == 'running' or system.state.all_positions() or runtime.close_requested:
                await asyncio.to_thread(runtime.tick, get_et_now(), system.status == 'running',
                                        earnings_filter.should_skip)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('Trading cycle failed')
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    system.state = load_state()
    if system.trader.api_key and system.trader.secret_key:
        runtime.reconcile()
    system._trading_task = asyncio.create_task(trading_loop())
    yield
    system._trading_task.cancel()
    try:
        await system._trading_task
    except asyncio.CancelledError:
        pass
    save_state(system.state)


app = FastAPI(title='Pulse V1', version='3.0.0', lifespan=lifespan)
allowed_origins = [origin.strip() for origin in os.getenv(
    'ALLOWED_ORIGINS',
    'https://alpaca-bot-v2.vercel.app,https://alpaca-bot-dashboard.vercel.app,http://localhost:8765'
).split(',') if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_credentials=False,
                   allow_methods=['*'], allow_headers=['*'])


@app.get('/')
async def root():
    return {'status': 'ok', 'service': 'Pulse V1'}


@app.get('/api/status')
async def get_status():
    uptime = ((datetime.utcnow() - system.start_time).total_seconds()
              if system.start_time else 0.0)
    return {
        'status': system.status, 'mode': system.mode, 'uptime': uptime,
        'daily_pnl': system.state.daily_pnl,
        'total_trades': system.state.trades_today,
        'active_positions': len(system.state.all_positions()),
        'portfolio_value': system.get_portfolio_value(),
        'buying_power': system.get_buying_power(),
        'reconciliation_error': runtime.error, 'last_scan_at': runtime.last_scan_at,
        'last_scan_error': runtime.last_scan_error, 'last_cycle_at': runtime.last_cycle_at,
    }


@app.get('/api/positions')
async def get_positions():
    return [{'symbol': p['symbol'], 'side': p['side'], 'entry': p['entry_price'],
             'current_price': p['current_price'], 'size': p['qty'],
             'pnl': p['unrealized_pl'], 'pnl_pct': p['unrealized_plpc']}
            for p in system.trader.get_positions()]


@app.get('/api/trades')
@app.get('/api/daily')
async def get_trades():
    return get_trade_summary()


@app.get('/api/trade-records')
def get_trade_records():
    return {'records': get_csv_trade_records(),
            'source': 'Durable CSV trade ledger; times shown in US Eastern'}


@app.get('/api/trade-logs')
def get_trade_logs():
    records = get_csv_trade_records()
    if not records:
        eastern = __import__('zoneinfo').ZoneInfo('America/New_York')
        recovered, positions = [], {}
        orders = sorted(system.trader.get_orders(status='closed'),
                        key=lambda order: str(order.get('filled_at') or ''))
        for order in orders:
            if not order.get('filled_qty') or not order.get('filled_avg_price'):
                continue
            filled_at = order.get('filled_at')
            if filled_at:
                if isinstance(filled_at, str):
                    filled_at = datetime.fromisoformat(filled_at.replace('Z', '+00:00'))
                time_et = filled_at.astimezone(eastern).strftime('%Y-%m-%d %H:%M:%S %Z')
            else:
                time_et = ''
            order_type = (order.get('type') or '').lower()
            symbol, side = order.get('symbol'), order.get('side')
            qty, price = float(order['filled_qty']), float(order['filled_avg_price'])
            signed = qty if side == 'buy' else -qty
            held, average = positions.get(symbol, (0.0, 0.0))
            if held == 0 or held * signed > 0:
                total = abs(held) + qty
                positions[symbol] = (held + signed, (average * abs(held) + price * qty) / total)
                event, pnl = 'ENTRY', None
            else:
                closed_qty = min(abs(held), qty)
                pnl = round((price - average) * closed_qty * (1 if held > 0 else -1), 2)
                remaining = held + signed
                positions[symbol] = (remaining, price if held * remaining < 0 else average)
                event = {'stop': 'SL', 'limit': 'TP'}.get(order_type, 'MARKET_EXIT')
            recovered.append({
                'time': filled_at.isoformat() if filled_at else '', 'time_et': time_et,
                'symbol': symbol, 'event': event, 'side': side, 'price': price,
                'shares': qty, 'pnl': pnl,
                'source': 'Recovered from Alpaca order history',
            })
        return sorted(recovered, key=lambda row: row['time'], reverse=True)
    return [{
        'time': row.get('timestamp'), 'time_et': row.get('entry_time_et'),
        'symbol': row.get('symbol'),
        'event': ('ENTRY_' + row.get('side', '').upper()) if row.get('status') == 'open'
                 else row.get('exit_reason_label'),
        'side': row.get('side'), 'price': row.get('exit_price') or row.get('entry_price'),
        'shares': row.get('shares'), 'pnl': row.get('pnl'),
    } for row in records]


@app.get('/api/closed-positions')
def get_closed_positions():
    summary = get_trade_summary()
    return {'total_closed': summary.get('total_trades', 0), **summary}


@app.get('/api/pnl-curve')
def get_pnl_curve():
    total = 0.0
    curve = []
    for row in reversed(get_csv_trade_records()):
        if row.get('status') == 'closed':
            total += row.get('pnl', 0)
            curve.append({'time': row.get('exit_time_et'), 'pnl': round(total, 2)})
    return curve


@app.get('/api/symbol-stats')
def get_symbol_stats():
    stats = {}
    for row in get_csv_trade_records():
        if row.get('status') != 'closed':
            continue
        item = stats.setdefault(row.get('symbol'), {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0})
        item['trades'] += 1
        item['wins' if row.get('pnl', 0) > 0 else 'losses'] += 1
        item['pnl'] += row.get('pnl', 0)
    return [{'symbol': symbol, **item,
             'win_rate': item['wins'] / item['trades'] * 100}
            for symbol, item in stats.items()]


@app.get('/api/weekly')
async def get_weekly_summary():
    return journal.get_weekly_summary()


@app.get('/api/journal')
async def get_journal():
    return journal.get_summary()


@app.get('/api/scan')
async def get_scan():
    return runtime.last_scan


@app.get('/api/clock')
async def get_clock():
    clock = system.trader.get_clock()
    if not clock:
        raise HTTPException(status_code=500, detail='Failed to fetch clock')
    return clock


@app.get('/api/admin/verify')
async def verify_admin(_=Depends(require_admin_key)):
    return {'admin': True}


@app.post('/api/start')
async def start_trading(_=Depends(require_admin_key)):
    if runtime.close_requested and system.state.all_positions():
        raise HTTPException(status_code=409, detail='Close-all is still pending')
    runtime.close_requested = False
    runtime.reconcile()
    if not runtime.ready:
        raise HTTPException(status_code=503, detail=runtime.error)
    system.status = 'running'
    system.mode = 'paper' if system.trader.paper else 'live'
    system.start_time = datetime.utcnow()
    return {'status': 'started', 'mode': system.mode}


@app.post('/api/stop')
async def stop_trading(_=Depends(require_admin_key)):
    system.status = 'stopped'
    return {'status': 'stopped', 'position_management': 'active'}


@app.post('/api/close-all', status_code=202)
async def close_all(_=Depends(require_admin_key)):
    system.status = 'stopped'
    runtime.close_requested = True
    runtime.reconcile()
    for position in system.state.all_positions():
        position.exit_reason = 'manual_close'
    save_state(system.state)
    runtime.manage_positions()
    return {'status': 'close_requested', 'remaining': len(system.state.all_positions()),
            'error': runtime.error}


@app.post('/api/positions/{symbol}/close', status_code=202)
async def close_position(symbol: str, _=Depends(require_admin_key)):
    symbol = symbol.strip().upper()
    runtime.reconcile()
    position = next((p for p in system.state.all_positions() if p.symbol == symbol), None)
    if position is None:
        raise HTTPException(status_code=404, detail='Open position not found')
    try:
        runtime.request_close(position, 'manual_close')
    except Exception as exc:
        logger.exception('Manual close failed for %s', symbol)
        raise HTTPException(status_code=502, detail='Position close request failed') from exc
    return {'status': 'close_requested', 'symbol': symbol, 'reason': 'manual_close'}


@app.post('/api/cancel-all')
async def cancel_all(_=Depends(require_admin_key)):
    system.status = 'stopped'
    try:
        for order in system.trader.open_orders():
            system.trader.trading_client.cancel_order_by_id(order['id'])
    except Exception as exc:
        raise HTTPException(status_code=502, detail='Order cancellation failed') from exc
    return {'status': 'cancellation_requested'}


if __name__ == '__main__':
    uvicorn.run('main:app', host='0.0.0.0', port=int(os.environ.get('PORT', 10000)),
                reload=False, log_level='info')
