"""Unit tests for signals/risk.py, per the Phase 3 test mandate: hand-computed
fixtures for RiskManagerAgent's deterministic rules 1, 3, 4, 6, 7, 8, 9.
"""
from __future__ import annotations

import pytest

from signals.risk import (
    compute_risk_verdict,
    correlation_adjusted_cap,
    drawdown_adjusted_risk_pct,
    jp_lot_feasibility,
    kelly_upper_bound,
    position_size_currency,
    tse_price_limit_band,
)


def test_position_size_currency_hand_computed():
    # risk_amount = 100000*0.01=1000; stop_distance=5; shares=200; notional=200*100=20000
    assert position_size_currency(100000, 1.0, 100, 95) == pytest.approx(20000.0)


def test_kelly_upper_bound_hand_computed():
    # b=1.5; f*=0.55-0.45/1.5=0.25; result=min(0.25*0.25,0.25)=0.0625
    assert kelly_upper_bound(0.55, 1.5, 1.0, cap=0.25) == pytest.approx(0.0625)


def test_kelly_upper_bound_never_exceeds_cap():
    assert kelly_upper_bound(0.95, 5.0, 1.0, cap=0.25) <= 0.25


def test_jp_lot_feasibility_hand_computed():
    result = jp_lot_feasibility(price=3000, position_size_currency_amount=200000)
    assert result.required_capital == pytest.approx(300000.0)
    assert result.feasible is False

    feasible = jp_lot_feasibility(price=3000, position_size_currency_amount=400000)
    assert feasible.feasible is True


def test_tse_price_limit_band_hand_computed():
    # prev_close=250 falls in the [200,300) tier -> +/-80
    assert tse_price_limit_band(250) == (170, 330)


def test_correlation_adjusted_cap_hand_computed():
    # max_combined = 1000*1.5=1500; headroom = 1500-800=700
    assert correlation_adjusted_cap(single_trade_cap=1000, correlated_open_exposure=800, cap_multiple=1.5) == pytest.approx(700.0)


def test_drawdown_adjusted_risk_pct_halves_above_threshold():
    assert drawdown_adjusted_risk_pct(1.0, current_drawdown_pct=20.0, threshold_pct=15.0) == pytest.approx(0.5)
    assert drawdown_adjusted_risk_pct(1.0, current_drawdown_pct=5.0, threshold_pct=15.0) == pytest.approx(1.0)


def test_compute_risk_verdict_normal_approve_case():
    result = compute_risk_verdict(
        equity=100000, entry_price=100, atr14=2, stop_multiple=2, proposed_stop_price=None, asset_class="us_equity"
    )
    assert result.risk_signal == "approve"
    assert result.conviction == 0.0
    assert result.max_position_size_currency == pytest.approx(25000.0)


def test_compute_risk_verdict_drawdown_reduces_size_not_veto():
    result = compute_risk_verdict(
        equity=100000,
        entry_price=100,
        atr14=2,
        stop_multiple=2,
        proposed_stop_price=None,
        asset_class="us_equity",
        current_drawdown_pct=20,
    )
    assert result.risk_signal == "reduce_size"
    assert result.max_position_size_currency == pytest.approx(12500.0)


def test_compute_risk_verdict_jp_lot_infeasible_hard_vetoes():
    result = compute_risk_verdict(
        equity=100000,
        entry_price=3000,
        atr14=50,
        stop_multiple=2,
        proposed_stop_price=None,
        asset_class="jp_equity",
        prev_close=3000,
    )
    assert result.risk_signal == "veto"
    assert result.structural_feasibility == "infeasible_lot_size"
    assert result.max_position_size_currency == 0.0


def test_compute_risk_verdict_jp_stop_outside_band_gets_overridden():
    result = compute_risk_verdict(
        equity=1_000_000,
        entry_price=250,
        atr14=5,
        stop_multiple=1.5,
        proposed_stop_price=150,  # outside the (170, 330) band
        asset_class="jp_equity",
        prev_close=250,
    )
    assert result.jp_limit_band_flag == "stop_outside_band"
    assert result.stop_loss_override_price == pytest.approx(170.0)
    assert result.risk_signal == "reduce_size"


def test_compute_risk_verdict_stacked_flags_drive_conviction_to_veto():
    # band=(170,330), width=160; entry=326 is 4 away from the upper edge
    # (2.5% of band width) -> limit_lock_risk. Stacked with drawdown (+0.3)
    # and correlation_cap (+0.2) and limit_lock (+0.3), conviction hits 1.0 --
    # and the resulting heavily-reduced position also fails the JP lot-size
    # check, so both the hard structural gate and the soft conviction
    # threshold agree on veto here (a realistic compound scenario, not an
    # artificially isolated single-rule case).
    result = compute_risk_verdict(
        equity=1_000_000,
        entry_price=326,
        atr14=5,
        stop_multiple=1.5,
        proposed_stop_price=None,
        asset_class="jp_equity",
        prev_close=250,
        current_drawdown_pct=20,
        correlated_open_exposure=100_000,
        correlation_cap_multiple=1.0,
    )
    assert result.jp_limit_band_flag == "limit_lock_risk"
    assert "drawdown_circuit_breaker (drawdown=20.0%)" in result.triggered_flags
    assert "correlation_cap" in result.triggered_flags
    assert result.conviction == pytest.approx(1.0)
    assert result.risk_signal == "veto"
    assert result.max_position_size_currency == 0.0


def test_compute_risk_verdict_conviction_capped_at_one():
    # non-JP assets can only accumulate drawdown (+0.3) and correlation (+0.2)
    # flags in this design (JP-specific flags don't apply) -- conviction
    # should never exceed what's actually triggered, and never exceed 1.0.
    result = compute_risk_verdict(
        equity=1_000_000,
        entry_price=100,
        atr14=2,
        stop_multiple=2,
        proposed_stop_price=None,
        asset_class="us_equity",
        current_drawdown_pct=20,
        correlated_open_exposure=1_000_000,
        correlation_cap_multiple=0.01,
    )
    assert result.conviction == pytest.approx(0.5)  # 0.3 (drawdown) + 0.2 (correlation), below the 0.7 veto threshold
    assert result.risk_signal == "reduce_size"
