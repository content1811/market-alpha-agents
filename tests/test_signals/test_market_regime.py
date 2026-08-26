"""Unit tests for signals/market_regime.py, per the Phase 2/3 test mandate:
hand-computed fixtures.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from signals.market_regime import compute_market_regime, percentile_rank


def test_percentile_rank_hand_computed():
    distribution = pd.Series(range(1, 11))  # 1..10
    assert percentile_rank(5, distribution) == pytest.approx(50.0)
    assert percentile_rank(10, distribution) == pytest.approx(100.0)
    assert percentile_rank(0, distribution) == pytest.approx(0.0)


def test_regime_breaker_activates_on_volatility_spike():
    rng = np.random.RandomState(0)
    calm = rng.normal(0, 0.005, 280)
    spike = rng.normal(0, 0.03, 20)  # last 20 days much more volatile
    returns = pd.Series(np.concatenate([calm, spike]))

    result = compute_market_regime(returns)

    assert result.vol_percentile >= 85.0
    assert result.regime_breaker_active is True
    assert result.position_size_ceiling_multiplier == pytest.approx(0.5)


def test_regime_breaker_inactive_in_calm_market():
    rng = np.random.RandomState(1)
    returns = pd.Series(rng.normal(0, 0.005, 300))

    result = compute_market_regime(returns)

    assert result.regime_breaker_active is False
    assert result.position_size_ceiling_multiplier == pytest.approx(1.0)


def test_breaker_thresholds_are_config_driven_not_hardcoded():
    rng = np.random.RandomState(2)
    returns = pd.Series(rng.normal(0, 0.01, 300))
    lenient = compute_market_regime(returns, breaker_percentile=99.9, breaker_multiplier=0.3)
    strict = compute_market_regime(returns, breaker_percentile=1.0, breaker_multiplier=0.3)
    assert lenient.regime_breaker_active is False
    assert strict.regime_breaker_active is True
    assert strict.position_size_ceiling_multiplier == pytest.approx(0.3)
