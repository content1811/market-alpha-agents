"""Unit tests for signals/squeeze.py, per the Phase 2 test mandate:
hand-computed fixtures.
"""
from __future__ import annotations

import pytest

from signals.squeeze import OptionRow, compute_squeeze, options_score


def test_options_score_fires_on_unusual_bullish_activity():
    rows = [OptionRow(strike=100, last_price=5.5, bid=5.0, ask=5.2, volume=600, open_interest=200)]
    # vol/oi = 600/200 = 3.0 >= 1.25, last_price(5.5) >= ask(5.2), vol>500, oi>100
    assert options_score(rows) == 1.0


def test_options_score_zero_when_liquidity_too_thin():
    rows = [OptionRow(strike=100, last_price=5.5, bid=5.0, ask=5.2, volume=50, open_interest=10)]
    assert options_score(rows) == 0.0


def test_options_score_zero_when_not_bullish_skew():
    rows = [OptionRow(strike=100, last_price=4.0, bid=5.0, ask=5.2, volume=600, open_interest=200)]  # last < ask
    assert options_score(rows) == 0.0


def test_options_score_skips_rows_with_no_ask_quote():
    rows = [OptionRow(strike=100, last_price=5.5, bid=0.0, ask=0.0, volume=600, open_interest=200)]
    assert options_score(rows) == 0.0


def test_compute_squeeze_full_data_hand_computed():
    # weighted_avg = 0.30*0.5 + 0.20*0.6 + 0.25*0.2 + 0.15*0.75 + 0.10*1.0
    #              = 0.15 + 0.12 + 0.05 + 0.1125 + 0.10 = 0.5325
    rows = [OptionRow(strike=100, last_price=5.5, bid=5.0, ask=5.2, volume=600, open_interest=200)]
    result = compute_squeeze(
        si_pct_of_float=20, days_to_cover=6, borrow_fee_rate_pct=10, utilization_pct=95, option_rows=rows
    )
    assert result.signal_score == pytest.approx(0.5325)
    assert result.confidence == pytest.approx(0.7)
    assert result.degraded_fields == []


def test_compute_squeeze_degraded_mode_renormalizes_not_zeros():
    # only options_score available -- signal_score should equal options_score
    # itself (renormalized over the only available weight), NOT be diluted
    # toward 0 by treating the missing FINRA/borrow-fee inputs as zero.
    rows = [OptionRow(strike=100, last_price=5.5, bid=5.0, ask=5.2, volume=600, open_interest=200)]
    result = compute_squeeze(
        si_pct_of_float=None, days_to_cover=None, borrow_fee_rate_pct=None, utilization_pct=None, option_rows=rows
    )
    assert result.signal_score == pytest.approx(1.0)
    assert result.confidence == pytest.approx(0.15)
    assert len(result.degraded_fields) == 4


def test_compute_squeeze_never_negative():
    result = compute_squeeze(si_pct_of_float=0, days_to_cover=0, borrow_fee_rate_pct=0, utilization_pct=0, option_rows=None)
    assert result.signal_score >= 0.0


def test_jp_confidence_floored_low():
    rows = [OptionRow(strike=100, last_price=5.5, bid=5.0, ask=5.2, volume=600, open_interest=200)]
    result = compute_squeeze(
        si_pct_of_float=20, days_to_cover=6, borrow_fee_rate_pct=10, utilization_pct=95, option_rows=rows, is_jp=True
    )
    assert result.confidence <= 0.2
