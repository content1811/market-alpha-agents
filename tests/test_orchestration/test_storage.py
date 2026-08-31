"""Tests for orchestration/storage.py."""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone

from agents.schemas import ComponentBreakdownRow, HoldingPeriod, ProfitTarget, StopLoss, SupervisorVerdict
from data.schema import AssetClass
from orchestration.storage import (
    get_outcome,
    get_recommendation,
    pending_outcomes,
    save_outcome,
    save_recommendation,
    update_human_decision,
)

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


def test_update_human_decision():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/recommendations.db"
        save_recommendation(db_path, FIXTURE_VERDICT)
        assert get_recommendation(db_path, "AAPL-2026-08-26")["human_decision"] is None
        update_human_decision(db_path, "AAPL-2026-08-26", "approved")
        assert get_recommendation(db_path, "AAPL-2026-08-26")["human_decision"] == "approved"


def test_save_and_get_outcome_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/outcomes.db"
        save_outcome(
            db_path, "AAPL-2026-08-26", actual_entry_price=300.0, actual_exit_price=311.0,
            exit_date="2026-09-02", exit_reason="target_hit", human_action="followed", realized_pnl=11.0,
        )
        row = get_outcome(db_path, "AAPL-2026-08-26")
        assert row is not None
        assert row["exit_reason"] == "target_hit"
        assert row["realized_pnl"] == 11.0


def test_pending_outcomes_flags_old_approved_unlogged_only():
    with tempfile.TemporaryDirectory() as tmp:
        rec_db, out_db = f"{tmp}/recommendations.db", f"{tmp}/outcomes.db"
        old_ts = datetime.now(timezone.utc) - timedelta(days=100)
        recent_ts = datetime.now(timezone.utc) - timedelta(days=5)

        old_unlogged = FIXTURE_VERDICT.model_copy(update={"recommendation_id": "AAPL-2026-05-20", "as_of_timestamp": old_ts})
        old_logged = FIXTURE_VERDICT.model_copy(update={"recommendation_id": "MSFT-2026-05-20", "as_of_timestamp": old_ts, "ticker": "MSFT"})
        old_rejected = FIXTURE_VERDICT.model_copy(update={"recommendation_id": "TSLA-2026-05-20", "as_of_timestamp": old_ts, "ticker": "TSLA"})
        recent_unlogged = FIXTURE_VERDICT.model_copy(update={"recommendation_id": "NVDA-2026-08-26", "as_of_timestamp": recent_ts, "ticker": "NVDA"})

        for v in (old_unlogged, old_logged, old_rejected, recent_unlogged):
            save_recommendation(rec_db, v)
        update_human_decision(rec_db, old_unlogged.recommendation_id, "approved")
        update_human_decision(rec_db, old_logged.recommendation_id, "approved")
        update_human_decision(rec_db, old_rejected.recommendation_id, "rejected")
        update_human_decision(rec_db, recent_unlogged.recommendation_id, "approved")
        save_outcome(out_db, old_logged.recommendation_id, 1.0, 1.0, "2026-05-25", "target_hit", "followed", 0.0)

        rows = pending_outcomes(rec_db, out_db, older_than_days=90)
        assert [r["recommendation_id"] for r in rows] == ["AAPL-2026-05-20"]
