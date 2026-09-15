"""Server-only Supabase persistence for the trade ledger."""
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def configured():
    return bool(os.getenv('SUPABASE_URL') and os.getenv('SUPABASE_SECRET_KEY'))


def _request(method, path, payload=None):
    url = os.environ['SUPABASE_URL'].rstrip('/') + '/rest/v1/' + path
    key = os.environ['SUPABASE_SECRET_KEY']
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {'apikey': key, 'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
    if method == 'POST':
        headers['Prefer'] = 'resolution=merge-duplicates,return=minimal'
    with urlopen(Request(url, data=body, headers=headers, method=method), timeout=10) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def upsert(row):
    if configured():
        _request('POST', 'trade_ledger?on_conflict=position_id', row)


def fetch_all():
    if not configured():
        return []
    return _request('GET', 'trade_ledger?select=*&order=entry_time.desc') or []

