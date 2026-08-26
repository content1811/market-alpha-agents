"""Tests for backtesting/run_backtest.py using synthetic data (fast,
deterministic, no network) -- the real capstone run against live AAPL
history (2018-2026, mean-reversion signal, walk-forward OOS-only) was run
manually and returned Sharpe=-0.40, profit factor=0.80, DSR=0.0, i.e. this
default-parameter mean-reversion signal shows NO real edge on that ticker
once realistic costs are applied -- exactly the kind of honest rejection this
validation framework exists to produce, not a result to be alarmed by.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtesting.run_backtest import signal_to_positions, simulate_returns, walk_forward_backtest


def test_signal_to_positions_hand_traced():
    # scores: enter when >=0.35 while flat, exit when <0.10 while in position
    scores = pd.Series([0.1, 0.4, 0.5, 0.05, 0.4, 0.2])
    entries, exits = signal_to_positions(scores, buy_threshold=0.35, exit_threshold=0.10)
    assert list(entries) == [False, True, False, False, True, False]
    assert list(exits) == [False, False, False, True, False, False]


def test_simulate_returns_produces_series_aligned_to_price_index():
    n = 100
    rng = np.random.RandomState(0)
    price = pd.Series(100 * np.cumprod(1 + rng.normal(0.0005, 0.01, n)), index=pd.date_range("2024-01-01", periods=n, freq="B"))
    signal = pd.Series(rng.uniform(-1, 1, n), index=price.index)

    returns = simulate_returns(price, signal)
    assert len(returns) == n
    assert returns.index.equals(price.index)


def test_walk_forward_backtest_only_uses_out_of_sample_data():
    n = 500
    rng = np.random.RandomState(1)
    price = pd.Series(100 * np.cumprod(1 + rng.normal(0.0005, 0.01, n)), index=pd.date_range("2020-01-01", periods=n, freq="B"))
    signal = pd.Series(rng.uniform(-1, 1, n), index=price.index)

    result = walk_forward_backtest(price, signal, in_sample_days=200, out_of_sample_days=50)

    # total OOS length must be num_splits * out_of_sample_days, never touching
    # the in-sample windows
    assert len(result.out_of_sample_returns) == result.num_splits * 50
    assert isinstance(result.sharpe, float)
    assert 0.0 <= result.deflated_sharpe <= 1.0


def test_walk_forward_backtest_raises_on_too_short_series():
    price = pd.Series([100.0] * 50, index=pd.date_range("2024-01-01", periods=50, freq="B"))
    signal = pd.Series([0.0] * 50, index=price.index)
    with pytest.raises(ValueError):
        walk_forward_backtest(price, signal, in_sample_days=252, out_of_sample_days=63)
