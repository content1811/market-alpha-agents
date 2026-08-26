"""Tests for alerting/triggers.py -- threshold checks and dedup cooldown."""
from __future__ import annotations

import tempfile
import time

from alerting.triggers import (
    AlertDeduplicator,
    composite_score_threshold,
    filing_match,
    rvol_price_spike,
    squeeze_risk_flag,
    stop_target_proximity,
)


def test_composite_score_threshold_fires_at_boundary():
    assert composite_score_threshold(0.70) is not None
    assert composite_score_threshold(-0.70) is not None
    assert composite_score_threshold(0.69) is None


def test_squeeze_risk_flag_fires_at_boundary():
    assert squeeze_risk_flag(0.6) is not None
    assert squeeze_risk_flag(0.59) is None


def test_stop_target_proximity_hand_computed():
    # price=98, stop=95, atr14=10 -> 0.5*10=5; |98-95|=3<=5 -> fires (high)
    alert = stop_target_proximity(price=98, stop_price=95, target_price=None, atr14=10)
    assert alert is not None
    assert alert.severity == "high"

    # price=98, target=120, atr14=10 -> |98-120|=22 > 5 -> no fire
    assert stop_target_proximity(price=98, stop_price=None, target_price=120, atr14=10) is None


def test_rvol_price_spike_equity_thresholds():
    assert rvol_price_spike(rvol=3.5, same_bar_return_pct=2.5, is_crypto=False) is not None
    assert rvol_price_spike(rvol=2.0, same_bar_return_pct=2.5, is_crypto=False) is None  # RVOL below threshold


def test_rvol_price_spike_crypto_uses_higher_thresholds():
    # would fire under equity thresholds (RVOL 3.5>=3, return 2.5%>=2%) but
    # crypto needs RVOL>=4x AND return>=4%
    assert rvol_price_spike(rvol=3.5, same_bar_return_pct=2.5, is_crypto=True) is None
    assert rvol_price_spike(rvol=4.5, same_bar_return_pct=4.5, is_crypto=True) is not None


def test_filing_match_severity_by_materiality():
    assert filing_match("8-K", is_material_event=True).severity == "high"
    assert filing_match("8-K", is_material_event=False).severity == "medium"


def test_dedup_blocks_within_cooldown_then_allows_after():
    with tempfile.TemporaryDirectory() as tmp:
        dedup = AlertDeduplicator(db_path=f"{tmp}/state.db", cooldown_hours=0.0003)  # ~1 second
        assert dedup.should_send("AAPL", "composite_score_threshold") is True
        dedup.record_sent("AAPL", "composite_score_threshold")
        assert dedup.should_send("AAPL", "composite_score_threshold") is False
        time.sleep(1.1)
        assert dedup.should_send("AAPL", "composite_score_threshold") is True
        dedup.close()


def test_dedup_is_per_symbol_and_per_trigger_type():
    with tempfile.TemporaryDirectory() as tmp:
        dedup = AlertDeduplicator(db_path=f"{tmp}/state.db", cooldown_hours=2.0)
        dedup.record_sent("AAPL", "composite_score_threshold")
        assert dedup.should_send("AAPL", "composite_score_threshold") is False
        assert dedup.should_send("AAPL", "squeeze_risk_flag") is True  # different trigger type
        assert dedup.should_send("TSLA", "composite_score_threshold") is True  # different symbol
        dedup.close()
