"""Unit tests for signals/ta/mean_reversion.py, per the Phase 2 test mandate
in docs/plan/section_orchestration.md section 3: hand-computed fixtures.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from signals.ta.mean_reversion import (
    bollinger_pct_b,
    compute_mean_reversion,
    rsi2,
    vwap_zscore,
    zscore_vs_ma,
)


def test_bollinger_pct_b_hand_computed():
    # closes = [10,12,11,13,15], window=5, k=2.
    # mean=12.2, population std (ddof=0, matches the `ta` library convention)
    # = sqrt(14.8/5) = 1.720465..., upper=15.64093, lower=8.75907
    # %B = (15-8.75907)/(15.64093-8.75907) = 0.906867
    closes = pd.Series([10.0, 12.0, 11.0, 13.0, 15.0])
    result = bollinger_pct_b(closes, window=5, k=2.0)
    assert result.iloc[-1] == pytest.approx(0.906867, abs=1e-5)


def test_rsi2_hand_computed():
    # Wilder EWM recursion (alpha=1/2, adjust=False) hand-traced in the PR
    # this test was written for -- see module docstring context. Values below
    # were independently derived step by step, not read off the function.
    closes = pd.Series([44.0, 44.5, 43.5, 44.0, 44.5, 45.0, 44.5, 46.0, 45.5, 47.0])
    result = rsi2(closes, window=2)
    assert result.iloc[1] == pytest.approx(100.0)
    assert result.iloc[2] == pytest.approx(20.0)
    assert result.iloc[3] == pytest.approx(55.555556, abs=1e-4)


def test_zscore_vs_ma_hand_computed():
    # closes[0:5]=[44,44.5,43.5,44,44.5], mean=44.1, sample std (ddof=1)=0.41833
    # z = (44.5-44.1)/0.41833 = 0.95618
    closes = pd.Series([44.0, 44.5, 43.5, 44.0, 44.5, 45.0])
    result = zscore_vs_ma(closes, window=5)
    assert result.iloc[4] == pytest.approx(0.956183, abs=1e-4)


def test_vwap_zscore_hand_computed():
    prices = pd.Series([100.0, 101.0, 99.0, 102.0])
    volumes = pd.Series([10.0, 20.0, 5.0, 15.0])
    # VWAP = sum(p*v)/sum(v) = (1000+2020+495+1530)/50 = 5045/50 = 100.9
    # stdev (ddof=1) of prices = std([100,101,99,102]) = 1.29099...
    # z = (102 - 100.9)/1.29099 = 0.85206
    result = vwap_zscore(prices, volumes)
    assert result == pytest.approx(0.85206, abs=1e-3)


def test_rsi2_score_gates_off_when_below_sma200():
    # fewer than 200 bars -> sma200 is NaN -> rsi2_score forced to 0 regardless
    # of how oversold RSI(2) looks, per section_agents.md section 1 rule 2.
    n = 60
    closes = pd.Series(100 - np.arange(n) * 0.5)  # steady downtrend, deeply oversold RSI(2)
    highs = closes + 0.3
    lows = closes - 0.3
    result = compute_mean_reversion(highs, lows, closes)
    assert result.rsi2_score == 0.0


def test_compute_mean_reversion_bounds_and_adx_gate():
    n = 250
    rng = np.random.RandomState(3)
    # mean-reverting series: oscillate around 100 with noise, not a trend
    closes = pd.Series(100 + np.sin(np.arange(n) / 5) * 3 + rng.normal(0, 0.3, n))
    highs = closes + 0.2
    lows = closes - 0.2

    result = compute_mean_reversion(highs, lows, closes)

    for score in (result.bb_score, result.rsi2_score, result.z_score, result.signal_score):
        assert -1.0 <= score <= 1.0
    assert 0.0 <= result.confidence <= 1.0
    assert 0.0 <= result.trend_confidence <= 1.0
    # oscillating series should NOT trip the strong-trend gate
    assert result.trend_confidence < 1.0


def test_compute_mean_reversion_suppressed_in_strong_trend():
    n = 250
    closes = pd.Series(100 * (1.01 ** np.arange(n)))  # clean monotonic uptrend
    highs = closes * 1.002
    lows = closes * 0.998

    result = compute_mean_reversion(highs, lows, closes)
    # ADX should be high enough to fully suppress the mean-reversion score
    assert result.trend_confidence == pytest.approx(1.0)
    assert result.signal_score == pytest.approx(0.0, abs=1e-9)
