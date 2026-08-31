"""Unit tests for signals/ta/seasonality.py, per the Phase 2 test mandate:
hand-computed fixtures for the bucket-score formula and its downstream users.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from signals.ta.seasonality import (
    _bucket_score,
    compute_seasonality,
    halving_cycle_phase,
    pead_score,
    turn_of_quarter_volatility_flag,
)


def test_bucket_score_forces_zero_below_min_sample_size():
    # n=5 < min_n=30 -> confidence_weight forced to 0 regardless of effect size
    small = pd.Series([0.01, 0.02, 0.015, 0.005, 0.01])
    score, n, t_stat = _bucket_score(small)
    assert score == 0.0
    assert n == 5
    assert t_stat == pytest.approx(4.706787, abs=1e-4)


def test_bucket_score_fires_when_n_and_t_both_pass():
    rng = np.random.RandomState(0)
    big = pd.Series(rng.normal(0.01, 0.005, 40))
    score, n, t_stat = _bucket_score(big)
    assert n == 40
    assert t_stat == pytest.approx(13.568884, abs=1e-3)
    # mean/std = 2.1454, clipped to [-1,1] since confidence_weight=1 (n>=30, |t|>=2)
    assert score == pytest.approx(1.0)


def test_pead_score_hand_computed():
    # most-recent-first per yfinance convention; most recent surprise (10.0)
    # is the max of the 6-value history -> percentile rank 1.0
    surprise = pd.Series([10.0, 5.0, -2.0, 3.0, 8.0, 1.0])
    # sue_pct=1.0 -> (1.0*2-1)=1.0; time_decay=1-10/90=0.888889
    assert pead_score(surprise, days_since_earnings=10) == pytest.approx(0.888889, abs=1e-5)


def test_pead_score_decays_to_zero_past_window():
    surprise = pd.Series([10.0, 5.0, -2.0, 3.0, 8.0, 1.0])
    assert pead_score(surprise, days_since_earnings=100, decay_days=90) == 0.0


def test_halving_cycle_phase_labels():
    assert halving_cycle_phase(date(2024, 6, 1)) == ("early-post-halving", 0.05)
    assert halving_cycle_phase(date(2026, 8, 26)) == ("mid-cycle", 0.0)


def test_turn_of_quarter_volatility_flag():
    assert turn_of_quarter_volatility_flag(date(2026, 3, 28)) is True
    assert turn_of_quarter_volatility_flag(date(2026, 3, 1)) is False
    assert turn_of_quarter_volatility_flag(date(2026, 4, 28)) is False  # not a quarter-end month


def test_signal_score_hard_capped_at_0_3():
    n = 500
    dates = pd.date_range("2018-01-01", periods=n, freq="B")
    rng = np.random.RandomState(2)
    # deliberately extreme, consistent returns so uncapped sub-scores would be huge
    returns = pd.Series(rng.normal(0.02, 0.002, n))
    result = compute_seasonality(returns, pd.Series(dates), as_of=date(2026, 8, 26))
    assert abs(result.signal_score) <= 0.3


def test_confidence_hard_capped_at_0_5():
    n = 2000  # large sample, would otherwise push size_confidence to 1.0
    dates = pd.date_range("2010-01-01", periods=n, freq="B")
    rng = np.random.RandomState(4)
    returns = pd.Series(rng.normal(0, 0.01, n))
    result = compute_seasonality(returns, pd.Series(dates), as_of=date(2026, 8, 26))
    assert result.confidence <= 0.5


def test_btc_halving_and_crypto_monthly_included_when_flagged():
    n = 800
    dates = pd.date_range("2022-01-01", periods=n, freq="D")
    rng = np.random.RandomState(6)
    returns = pd.Series(rng.normal(0, 0.02, n))
    result = compute_seasonality(returns, pd.Series(dates), as_of=date(2026, 8, 26), is_crypto=True, is_btc=True)
    assert result.halving_phase is not None
    assert result.crypto_monthly_score is not None
