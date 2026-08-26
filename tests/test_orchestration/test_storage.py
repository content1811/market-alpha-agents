"""Tests for orchestration/storage.py."""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone

from agents.schemas import ComponentBreakdownRow, HoldingPeriod, ProfitTarget, StopLoss, SupervisorVerdict
from data.schema import AssetClass
from orchestration.storage import get_recommendation, save_recommendation

FIXTURE_VERDICT = SupervisorVerdict(
    recommendation_id="AAPL-2026-08-26",
    asset_class=AssetClass.US_EQUITY,
    ticker="AAPL",
    as_of_timestamp=datetime.now(timezone.utc),
    final_call="BUY",
    blended_score=0.42,
    overall_confidence=0.65,
    component_breakdown=[ComponentBreakdownRow(agent="TrendMomentumAgent", score=0.6, confidence=0.8, weight=0.28, contribution=0.25)],
    disagreement_penalty_applied=0.1,
    risk_manager_override="none",
    suggested_holding_period=HoldingPeriod(min_days=3, max_days=10, unit="trading_days"),
    stop_loss=StopLoss(method="structure", value=290.0, price_level=290.0),
    profit_target=ProfitTarget(method="structure", value=311.0, price_level=311.0),
    max_position_size_currency=21460.09,
    rationale="Test rationale.",
)


def test_save_and_get_recommendation_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/recommendations.db"
        save_recommendation(db_path, FIXTURE_VERDICT)
        row = get_recommendation(db_path, "AAPL-2026-08-26")
        assert row is not None
        assert row["ticker"] == "AAPL"
        assert row["final_call"] == "BUY"
        assert row["blended_score"] == 0.42


def test_get_missing_recommendation_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/recommendations.db"
        assert get_recommendation(db_path, "NOPE-2026-01-01") is None


def test_save_recommendation_upserts_on_same_id():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/recommendations.db"
        save_recommendation(db_path, FIXTURE_VERDICT)
        updated = FIXTURE_VERDICT.model_copy(update={"final_call": "SELL", "blended_score": -0.5})
        save_recommendation(db_path, updated)
        row = get_recommendation(db_path, "AAPL-2026-08-26")
        assert row["final_call"] == "SELL"
        assert row["blended_score"] == -0.5
