"""Unit tests for signals/volatility_volume.py, per the Phase 2 test mandate:
hand-computed fixtures where tractable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from signals.volatility_volume import compute_volatility_volume, point_of_control, rvol


def test_rvol_hand_computed():
    # avg_volume[i] = mean(volume[i-3:i]), excluding day i itself
    volume = pd.Series([100.0, 200.0, 150.0, 300.0, 250.0, 180.0])
    result = rvol(volume, lookback=3)
    assert result.iloc[3] == pytest.approx(2.0)          # 300 / mean(100,200,150)=150
    assert result.iloc[4] == pytest.approx(1.153846, abs=1e-5)  # 250 / mean(200,150,300)=216.667
    assert result.iloc[5] == pytest.approx(0.771429, abs=1e-5)  # 180 / mean(150,300,250)=233.333


def test_point_of_control_finds_higher_volume_cluster():
    # two clusters: low-volume around 100, high-volume around 110 -> POC near 110
    high = pd.Series([100.5] * 5 + [110.5] * 5)
    low = pd.Series([99.5] * 5 + [109.5] * 5)
    close = pd.Series([100.0] * 5 + [110.0] * 5)
    volume = pd.Series([10.0] * 5 + [100.0] * 5)
    poc = point_of_control(high, low, close, volume, bins=20)
    assert poc == pytest.approx(109.75, abs=0.5)


def test_vol_conf_multiplier_bounds():
    n = 100
    rng = np.random.RandomState(1)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, n)))
    high, low = close * 1.005, close * 0.995
    volume = pd.Series(rng.uniform(1000, 2000, n))

    result = compute_volatility_volume(high, low, close, volume)

    assert -1.0 <= result.signal_score <= 1.0
    assert 0.0 <= result.rvol_score <= 1.0
    assert 0.0 <= result.confidence <= 1.0
    assert result.atr14 > 0
    # multiplier can exceed 1.0 on strong readings per the spec, but must be >= 0.5 - eps
    assert result.vol_conf_multiplier >= 0.4


def test_volume_spike_raises_rvol_and_multiplier():
    n = 30
    close = pd.Series(np.full(n, 100.0))
    high, low = close * 1.01, close * 0.99
    volume = pd.Series(np.full(n, 1000.0))
    volume.iloc[-1] = 6000.0  # 6x spike on the final bar

    result = compute_volatility_volume(high, low, close, volume)
    assert result.rvol_value > 5.0
    assert result.rvol_score == pytest.approx(1.0)  # clipped ceiling at RVOL>=5x per spec
