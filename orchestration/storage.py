"""storage/recommendations.db and storage/outcomes.db read/write, per
docs/plan/section_orchestration.md section 2 ("append-only log of every
scored recommendation, keyed by recommendation_id == LangGraph thread_id")
and section 3 Phase 7 (outcomes joined back to a recommendation by that same
id). `update_human_decision` is the only writer of the `human_decision`
column, and is only ever called from ui/review_cli.py's approve|reject flow,
after orchestration/graph.py's approval_gate interrupt() has actually been
resumed -- never speculatively before that.
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


def update_human_decision(db_path: str, recommendation_id: str, decision: str) -> None:
    init_recommendations_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE recommendations SET human_decision = ? WHERE recommendation_id = ?", (decision, recommendation_id)
    )
    conn.commit()
    conn.close()


def init_outcomes_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS outcomes (
            recommendation_id TEXT PRIMARY KEY,
            actual_entry_price REAL,
            actual_exit_price REAL,
            exit_date TEXT,
            exit_reason TEXT,
            human_action TEXT,
            realized_pnl REAL,
            logged_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


def save_outcome(
    db_path: str,
    recommendation_id: str,
    actual_entry_price: float | None,
    actual_exit_price: float | None,
    exit_date: str | None,
    exit_reason: str | None,
    human_action: str,
    realized_pnl: float | None,
) -> None:
    init_outcomes_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO outcomes
           (recommendation_id, actual_entry_price, actual_exit_price, exit_date, exit_reason,
            human_action, realized_pnl, logged_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT (recommendation_id) DO UPDATE SET
             actual_entry_price=excluded.actual_entry_price, actual_exit_price=excluded.actual_exit_price,
             exit_date=excluded.exit_date, exit_reason=excluded.exit_reason,
             human_action=excluded.human_action, realized_pnl=excluded.realized_pnl,
             logged_at=excluded.logged_at""",
        (recommendation_id, actual_entry_price, actual_exit_price, exit_date, exit_reason, human_action, realized_pnl),
    )
    conn.commit()
    conn.close()


def get_outcome(db_path: str, recommendation_id: str) -> dict | None:
    init_outcomes_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM outcomes WHERE recommendation_id = ?", (recommendation_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def pending_outcomes(recommendations_db_path: str, outcomes_db_path: str, older_than_days: float) -> list[dict]:
    """review_cli.py pending-outcomes --older-than: approved recommendations
    with no matching outcomes row yet, older than `older_than_days`, per
    section_orchestration.md section 3 Phase 7 (c). Excludes rejected and
    already-logged recommendations by construction (the LEFT JOIN + WHERE
    below), not as a separate filter step."""
    init_recommendations_db(recommendations_db_path)
    init_outcomes_db(outcomes_db_path)
    rec_conn = sqlite3.connect(recommendations_db_path)
    rec_conn.row_factory = sqlite3.Row
    approved = rec_conn.execute(
        "SELECT recommendation_id, ticker, as_of_timestamp, final_call FROM recommendations "
        "WHERE human_decision = 'approved' AND as_of_timestamp <= datetime('now', ?)",
        (f"-{older_than_days} days",),
    ).fetchall()
    rec_conn.close()

    out_conn = sqlite3.connect(outcomes_db_path)
    logged_ids = {row[0] for row in out_conn.execute("SELECT recommendation_id FROM outcomes")}
    out_conn.close()

    return [dict(row) for row in approved if row["recommendation_id"] not in logged_ids]
