"""Tests for backtesting/graduation_gate.py using hand-constructed
WalkForwardBacktestResult fixtures (no network / real backtest needed --
this only exercises evaluate_strategy's threshold logic in isolation)."""
from __future__ import annotations

import pandas as pd
import pytest

from backtesting.graduation_gate import MIN_PROFIT_FACTOR, evaluate_strategy
from backtesting.run_backtest import WalkForwardBacktestResult

CONFIG = {
    "backtesting": {
        "robustness_gates": {
            "min_deflated_sharpe": 0.5,
            "max_pbo": 0.4,
            "min_track_record_days": 180,
        }
    }
}


def _result(
    num_days: int = 200,
    sharpe: float = 1.2,
    profit_factor: float = 2.0,
    max_drawdown: float = -0.1,
    calmar: float = 1.0,
    deflated_sharpe: float = 0.6,
    min_track_record_length: float = 150.0,
) -> WalkForwardBacktestResult:
    return WalkForwardBacktestResult(
        out_of_sample_returns=pd.Series([0.001] * num_days),
        sharpe=sharpe,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        calmar=calmar,
        deflated_sharpe=deflated_sharpe,
        min_track_record_length=min_track_record_length,
        num_splits=num_days // 63 or 1,
    )


def test_clearly_passing_strategy_graduates():
    result = _result()
    graduation = evaluate_strategy(result, num_trials=1, pbo=0.2, config=CONFIG)
    assert graduation.passed is True
    assert graduation.reasons == []
    assert graduation.max_drawdown == -0.1
    assert graduation.calmar_ratio == 1.0


def test_clearly_failing_strategy_reports_every_specific_reason():
    # Fails all four hard gates at once: low DSR, high PBO, short track
    # record (both the config floor and the dynamic MinTRL requirement),
    # and a weak profit factor.
    result = _result(
        num_days=100,
        profit_factor=1.1,
        deflated_sharpe=0.0,
        min_track_record_length=float("inf"),
    )
    graduation = evaluate_strategy(result, num_trials=50, pbo=0.75, config=CONFIG)

    assert graduation.passed is False
    assert len(graduation.reasons) == 5
    assert any("Deflated Sharpe Ratio" in r for r in graduation.reasons)
    assert any("Probability of Backtest Overfitting" in r for r in graduation.reasons)
    assert any("minimum required by config" in r for r in graduation.reasons)
    assert any("Minimum Track Record Length" in r for r in graduation.reasons)
    assert any("Profit factor" in r for r in graduation.reasons)


def test_fails_only_on_profit_factor_when_everything_else_passes():
    result = _result(profit_factor=1.5)  # must be strictly > 1.5, not >=
    graduation = evaluate_strategy(result, num_trials=1, pbo=0.1, config=CONFIG)

    assert graduation.passed is False
    assert graduation.reasons == [f"Profit factor 1.500 does not exceed the required {MIN_PROFIT_FACTOR}"]


def test_fails_only_on_pbo_when_everything_else_passes():
    result = _result()
    graduation = evaluate_strategy(result, num_trials=1, pbo=0.41, config=CONFIG)

    assert graduation.passed is False
    assert graduation.reasons == ["Probability of Backtest Overfitting 0.410 exceeds the maximum allowed 0.400"]


def test_drawdown_and_calmar_never_gate_pass_fail():
    # Deep drawdown, terrible Calmar -- point 5 is "eyeballed", not a hard
    # gate, so a strategy passing every other check must still pass.
    result = _result(max_drawdown=-0.9, calmar=-5.0)
    graduation = evaluate_strategy(result, num_trials=1, pbo=0.1, config=CONFIG)

    assert graduation.passed is True
    assert graduation.max_drawdown == -0.9
    assert graduation.calmar_ratio == -5.0
