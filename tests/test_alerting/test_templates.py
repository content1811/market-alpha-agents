"""Tests for alerting/templates.py. A real SupervisorVerdict from a live
pipeline run was already formatted and delivered via desktop_notify -- these
use a fixture verdict to keep the test fast/deterministic."""
from __future__ import annotations

from datetime import datetime, timezone

from agents.schemas import ComponentBreakdownRow, HoldingPeriod, ProfitTarget, StopLoss, SupervisorVerdict
from alerting.templates import (
    format_composite_signal_alert,
    format_eod_summary,
    format_filing_alert,
    format_monthly_performance_digest,
    format_squeeze_risk_alert,
)
from data.schema import AssetClass

FIXTURE_VERDICT = SupervisorVerdict(
    recommendation_id="AAPL-2026-08-26",
    asset_class=AssetClass.US_EQUITY,
    ticker="AAPL",
    as_of_timestamp=datetime.now(timezone.utc),
    final_call="BUY",
    blended_score=0.42,
    overall_confidence=0.65,
    component_breakdown=[
        ComponentBreakdownRow(agent="TrendMomentumAgent", score=0.6, confidence=0.8, weight=0.28, contribution=0.25),
        ComponentBreakdownRow(agent="MeanReversionAgent", score=0.1, confidence=0.5, weight=0.18, contribution=0.05),
    ],
    disagreement_penalty_applied=0.1,
    risk_manager_override="none",
    suggested_holding_period=HoldingPeriod(min_days=3, max_days=10, unit="trading_days"),
    stop_loss=StopLoss(method="structure", value=290.0, price_level=290.0),
    profit_target=ProfitTarget(method="structure", value=311.0, price_level=311.0),
    max_position_size_currency=21460.09,
    rationale="TrendMomentum bullish, MeanReversion mildly bullish, no conflict. Manual analysis only.",
)


def test_format_composite_signal_alert_contains_key_fields():
    message = format_composite_signal_alert(FIXTURE_VERDICT, "AAPL (Apple)")
    assert "🟢" in message
    assert "BUY signal — AAPL (Apple)" in message
    assert "Score: +0.42" in message
    assert "Confidence: 0.65" in message
    assert "TrendMomentumAgent" in message
    assert "no order was placed" in message


def test_format_filing_alert():
    message = format_filing_alert("NVDA", "8-K", "Item 5.02 (officer departure)", "2026-08-26 16:02 ET", "https://sec.gov/x")
    assert "New 8-K filed — NVDA" in message
    assert "https://sec.gov/x" in message


def test_format_squeeze_risk_alert():
    message = format_squeeze_risk_alert("XYZ", 0.64, 34, 8.1, 12)
    assert "Squeeze-risk watch — XYZ" in message
    assert "0.64" in message


def test_format_eod_summary():
    message = format_eod_summary(
        "2026-08-26",
        {"US": "AAPL HOLD (0.12) | NVDA BUY (0.61)", "JP": "7203.T BUY (0.78)"},
        "J-Quants OK, Binance OK",
    )
    assert "Daily Summary — 2026-08-26" in message
    assert "US: AAPL HOLD" in message
    assert "Pipeline health: J-Quants OK" in message


def test_format_monthly_performance_digest_includes_reality_check():
    message = format_monthly_performance_digest(
        "August 2026", 0.114, 0.6, 0.8, -0.092, 0.14, 0.7, 24, 0.46
    )
    assert "CAGR (annualized) 11.4%" in message
    assert "50%+" in message
    assert "capital preservation" in message
