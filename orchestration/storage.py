"""storage/recommendations.db read/write, per docs/plan/section_orchestration.md
section 2: "append-only log of every scored recommendation, keyed by
recommendation_id (== LangGraph thread_id)". Outcome logging (storage/outcomes.db,
Phase 7's review_cli.py log-outcome) is not implemented yet -- that needs the
human-approval gate this module doesn't include (see README).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from agents.schemas import SupervisorVerdict


def init_recommendations_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS recommendations (
            recommendation_id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            as_of_timestamp TEXT NOT NULL,
            final_call TEXT NOT NULL,
            blended_score REAL NOT NULL,
            overall_confidence REAL NOT NULL,
            max_position_size_currency REAL NOT NULL,
            rationale TEXT NOT NULL,
            full_verdict_json TEXT NOT NULL,
            human_decision TEXT
        )"""
    )
    conn.commit()
    conn.close()


def save_recommendation(db_path: str, verdict: SupervisorVerdict) -> None:
    init_recommendations_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO recommendations
           (recommendation_id, ticker, asset_class, as_of_timestamp, final_call,
            blended_score, overall_confidence, max_position_size_currency, rationale, full_verdict_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (recommendation_id) DO UPDATE SET
             final_call=excluded.final_call, blended_score=excluded.blended_score,
             overall_confidence=excluded.overall_confidence,
             max_position_size_currency=excluded.max_position_size_currency,
             rationale=excluded.rationale, full_verdict_json=excluded.full_verdict_json""",
        (
            verdict.recommendation_id,
            verdict.ticker,
            verdict.asset_class.value,
            verdict.as_of_timestamp.isoformat(),
            verdict.final_call,
            verdict.blended_score,
            verdict.overall_confidence,
            verdict.max_position_size_currency,
            verdict.rationale,
            verdict.model_dump_json(),
        ),
    )
    conn.commit()
    conn.close()


def get_recommendation(db_path: str, recommendation_id: str) -> dict | None:
    init_recommendations_db(db_path)  # a lookup before anything was ever saved must not raise
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM recommendations WHERE recommendation_id = ?", (recommendation_id,)).fetchone()
    conn.close()
    return dict(row) if row else None
