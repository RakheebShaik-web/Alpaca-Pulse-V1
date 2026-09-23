"""Exercise the actual reporting endpoints without starting broker connections."""
import ast
from datetime import datetime
from pathlib import Path

import pytest


@pytest.mark.parametrize('pnls, expected', [([1.93, -43.89, -49.51], 33.3),
                                          ([10], 100.0), ([-10], 0.0), ([], 0.0)])
def test_closed_positions_win_rate_matches_counts(pnls, expected):
    tree = ast.parse((Path(__file__).parents[1] / 'main.py').read_text())
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in ('summarize_closed_records', 'get_trades', 'get_closed_positions')]
    for node in functions:
        node.decorator_list = []
    scope = {
        'get_trade_summary': lambda: {'total_trades': 0, 'wins': 0, 'losses': 0},
        'get_et_now': lambda: datetime(2026, 9, 16),
        'get_csv_trade_records': lambda: [{'pnl': p, 'status': 'closed'} for p in pnls],
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), scope)
    result = scope['get_closed_positions']()
    assert result['win_rate'] == expected
    assert result['total_closed'] == len(pnls)
