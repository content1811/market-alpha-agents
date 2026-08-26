"""Unit tests for signals/crypto_composite.py, per the Phase 2 test mandate:
hand-computed fixtures.
"""
from __future__ import annotations

import pytest

from signals.crypto_composite import compute_crypto_derivatives, compute_onchain, mvrv_band_score


def test_compute_crypto_derivatives_hand_computed():
    # annualized = rate*3*365: [109.5, 131.4, 98.55, 109.5, 164.25] (in %, i.e. *100 dropped -- using raw fraction*1095)
    # mean=0.12264, population std=0.023381, funding_z=(0.16425-0.12264)/0.023381=1.77949
    # funding_score = clip(-1.77949/2, -1, 1) = -0.889757 (approx)
    result = compute_crypto_derivatives(
        funding_rate_history=[0.0001, 0.00012, 0.00009, 0.0001, 0.00015],
        current_price=110.0,
        prior_price=100.0,
        current_oi=1000.0,
        prior_oi=900.0,
    )
    assert result.funding_score == pytest.approx(-0.889757, abs=1e-3)
    assert result.oi_score == pytest.approx(1.0)  # price up, OI up -> trend confirmation
    assert result.skew_score == 0.0  # skew_z=None -> skipped, not guessed
    assert result.squeeze_risk_flag is False
    # signal_score = (0.4*funding_score + 0.35*1.0) / 0.75 (skew_weight=0, excluded from denominator)
    assert result.signal_score == pytest.approx(-0.007870, abs=1e-4)


def test_squeeze_risk_flag_fires_on_price_down_oi_up():
    result = compute_crypto_derivatives(
        funding_rate_history=[0.0001] * 5,
        current_price=95.0,
        prior_price=100.0,
        current_oi=1100.0,
        prior_oi=1000.0,
    )
    assert result.squeeze_risk_flag is True
    assert result.oi_score == 0.0  # "flag, no fixed sign" per section_agents.md section 7


def test_skew_included_when_provided():
    with_skew = compute_crypto_derivatives(
        funding_rate_history=[0.0001] * 5,
        current_price=100.0,
        prior_price=100.0,
        current_oi=1000.0,
        prior_oi=1000.0,
        skew_z=2.0,
    )
    without_skew = compute_crypto_derivatives(
        funding_rate_history=[0.0001] * 5,
        current_price=100.0,
        prior_price=100.0,
        current_oi=1000.0,
        prior_oi=1000.0,
        skew_z=None,
    )
    assert with_skew.skew_score == pytest.approx(-1.0)  # clip(-2.0/1.5, -1, 1)
    assert without_skew.skew_score == 0.0
    assert with_skew.signal_score != without_skew.signal_score


def test_mvrv_band_score_boundaries():
    assert mvrv_band_score(0.5) == 95.0
    assert mvrv_band_score(1.5) == 70.0
    assert mvrv_band_score(3.0) == 50.0
    assert mvrv_band_score(5.0) == 20.0
    assert mvrv_band_score(8.0) == 5.0


def test_compute_onchain_hand_computed():
    # onchain_raw = 0.30*70 + 0.20*60 + 0.20*70 + 0.15*50 + 0.05*0 + 0.10*0
    #             = 21 + 12 + 14 + 7.5 = 54.5 -> signal_score = 0.545
    result = compute_onchain(mvrv=1.5, sopr_score=60, flow_score=70, whale_score=50, addr_divergence_score=0, unlock_penalty=0)
    assert result.signal_score == pytest.approx(0.545)
    assert result.confidence == pytest.approx(0.6)


def test_compute_onchain_bounds():
    result = compute_onchain(mvrv=10.0, sopr_score=-100, flow_score=-100, whale_score=-100, addr_divergence_score=-100, unlock_penalty=-100)
    assert -1.0 <= result.signal_score <= 1.0
