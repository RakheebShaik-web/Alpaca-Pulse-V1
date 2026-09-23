"""Entry requirements must not be bypassed by unrelated score points."""
from unittest.mock import Mock

import pandas as pd
import pytest

from config import config
from institutional_strategy import InstitutionalStrategy


@pytest.fixture
def candidate(monkeypatch):
    monkeypatch.setattr(config, 'market_alignment_filter', False)
    monkeypatch.setattr(config, 'regime_filter', True)
    monkeypatch.setattr(config, 'min_volume_mult', 1.0)
    monkeypatch.setattr(config, 'min_score_to_trade', 4)
    feed = Mock()
    feed.get_bars_yfinance.return_value = pd.DataFrame({'Close': [97.5, 98.]})
    feed.get_latest_price.return_value = 98.
    feed.get_volume_ratio.return_value = 2.
    feed.get_adx.return_value = 20.
    feed.get_atr.return_value = .5
    strategy = InstitutionalStrategy(feed)
    strategy.calculate_vwap_bands = Mock(return_value={
        'vwap': 100., 'upper': 101.5, 'lower': 98.5, 'std_dev': 1.})
    strategy.calculate_opening_range = Mock(return_value={
        'is_narrow': True, 'range_pct': .2})
    strategy.is_execution_window = Mock(return_value=True)
    return strategy


def test_valid_candidate_still_qualifies(candidate):
    assert candidate.generate_signal('AAPL') is not None


@pytest.mark.parametrize('ratio', [.5, float('nan'), float('inf')])
def test_volume_confirmation_is_required(candidate, ratio):
    candidate.data_feed.get_volume_ratio.return_value = ratio
    assert candidate.generate_signal('AAPL') is None
    assert candidate.last_rejection == 'insufficient_or_invalid_volume'


def test_narrow_opening_range_is_required(candidate):
    candidate.calculate_opening_range.return_value = {'is_narrow': False, 'range_pct': 1.2}
    assert candidate.generate_signal('AAPL') is None
    assert candidate.last_rejection == 'opening_range_not_narrow'


@pytest.mark.parametrize('adx', [float('nan'), float('inf'), -1.])
def test_invalid_regime_indicator_cannot_qualify(candidate, adx):
    candidate.data_feed.get_adx.return_value = adx
    assert candidate.generate_signal('AAPL') is None
    assert candidate.last_rejection == 'trend_regime_or_missing_adx'
