"""Tests for backtesting/robustness.py. sharpe_ratio/profit_factor/
max_drawdown/calmar_ratio are hand-computed fixtures. DSR/MinTRL/PBO are
graduate-level formulas implemented from their published definitions (no
independently-sourced numeric worked example was available to hand-verify
against -- see robustness.py's module docstring) -- these are tested against
documented monotonicity/sanity properties instead, which is a real but
weaker form of verification than an exact fixture; flagged accordingly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtesting.robustness import (
    calmar_ratio,
    deflated_sharpe_ratio,
    max_drawdown,
    minimum_track_record_length,
    probability_of_backtest_overfitting,
    profit_factor,
    sharpe_ratio,
)

FIXTURE_RETURNS = pd.Series([0.01, 0.02, -0.01, 0.015, 0.005])


def test_sharpe_ratio_hand_computed():
    # mean=0.008, sample std(ddof=1)=0.0115109... ; sharpe = mean/std*sqrt(252)
    assert sharpe_ratio(FIXTURE_RETURNS) == pytest.approx(11.0327, abs=1e-3)


def test_profit_factor_hand_computed():
    # gains=0.01+0.02+0.015+0.005=0.05; losses=0.01; pf=5.0
    assert profit_factor(FIXTURE_RETURNS) == pytest.approx(5.0)


def test_max_drawdown_hand_computed():
    equity = (1 + FIXTURE_RETURNS).cumprod()
    assert max_drawdown(equity) == pytest.approx(-0.01, abs=1e-6)


def test_calmar_ratio_positive_for_positive_drift():
    assert calmar_ratio(FIXTURE_RETURNS) > 0


# --- DSR sanity properties ---

def test_dsr_higher_with_fewer_trials_same_returns():
    rng = np.random.RandomState(0)
    returns = pd.Series(rng.normal(0.001, 0.01, 500))
    few_trials = deflated_sharpe_ratio(returns, num_trials=1, trial_sharpe_std=0.5)
    many_trials = deflated_sharpe_ratio(returns, num_trials=1000, trial_sharpe_std=0.5)
    assert few_trials >= many_trials


def test_dsr_in_valid_probability_range():
    rng = np.random.RandomState(1)
    returns = pd.Series(rng.normal(0.001, 0.01, 300))
    dsr = deflated_sharpe_ratio(returns, num_trials=50, trial_sharpe_std=0.5)
    assert 0.0 <= dsr <= 1.0


def test_dsr_low_for_mediocre_strategy_with_many_trials():
    rng = np.random.RandomState(2)
    returns = pd.Series(rng.normal(0.0001, 0.02, 100))  # weak edge, short history
    dsr = deflated_sharpe_ratio(returns, num_trials=500, trial_sharpe_std=0.5)
    assert dsr < 0.5


# --- MinTRL sanity properties ---

def test_mintrl_shorter_for_higher_sharpe():
    rng = np.random.RandomState(3)
    strong = pd.Series(rng.normal(0.003, 0.005, 300))
    weak = pd.Series(rng.normal(0.0005, 0.01, 300))
    assert minimum_track_record_length(strong) < minimum_track_record_length(weak)


def test_mintrl_infinite_when_sharpe_below_benchmark():
    returns = pd.Series(np.full(100, -0.001))
    assert minimum_track_record_length(returns, benchmark_sharpe=0.0) == float("inf")


# --- PBO sanity properties ---

def test_pbo_near_half_for_pure_noise_variants():
    rng = np.random.RandomState(4)
    # 6 variants, all pure iid noise with identical distribution -- no real
    # difference between them, so picking the "best" in-sample is luck, and
    # CSCV theory predicts PBO should land close to 0.5 (coin-flip).
    variants = [pd.Series(rng.normal(0, 0.01, 240)) for _ in range(6)]
    result = probability_of_backtest_overfitting(variants, num_blocks=8)
    assert 0.3 <= result.pbo <= 0.7


def test_pbo_low_for_genuinely_best_variant():
    rng = np.random.RandomState(5)
    # one variant has a real, persistent edge; the rest are pure noise --
    # the genuine variant should keep winning both IS and OOS, giving low PBO.
    genuine = pd.Series(rng.normal(0.003, 0.005, 240))
    noise = [pd.Series(rng.normal(0, 0.01, 240)) for _ in range(5)]
    result = probability_of_backtest_overfitting([genuine] + noise, num_blocks=8)
    assert result.pbo < 0.3


def test_pbo_requires_at_least_two_variants():
    with pytest.raises(ValueError):
        probability_of_backtest_overfitting([pd.Series([0.01] * 100)], num_blocks=4)


def test_pbo_requires_even_num_blocks():
    with pytest.raises(ValueError):
        probability_of_backtest_overfitting([pd.Series([0.01] * 100), pd.Series([0.02] * 100)], num_blocks=5)
