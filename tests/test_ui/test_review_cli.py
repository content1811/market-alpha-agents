"""Tests for ui/review_cli.py. Alert senders are monkeypatched (not mocked at
the HTTP layer -- alerting/telegram_bot.py and desktop_notify.py already have
their own direct tests) so these tests assert review_cli's own dispatch logic
-- approve sends, reject doesn't -- without popping a real macOS notification
or depending on a configured Telegram bot on every test run.
"""
from __future__ import annotations

import argparse
import sqlite3
import tempfile
from pathlib import Path

import pytest

import ui.review_cli as review_cli
from data.connectors.us_equities_yfinance import YFinanceSource
from data.schema import AssetClass
from orchestration.graph import run_for_ticker
from orchestration.storage import get_outcome, get_recommendation, save_recommendation, update_human_decision
from tests.test_agents.test_mean_reversion_agent import FakeLLM
from tests.test_orchestration.test_storage import FIXTURE_VERDICT

RATIONALE_RESPONSE = '{"rationale": "Test rationale citing the computed numbers, under any length limit."}'


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    rec_db = str(tmp_path / "recommendations.db")
    out_db = str(tmp_path / "outcomes.db")
    ckpt_db = str(tmp_path / "checkpoints.db")
    monkeypatch.setattr(review_cli, "RECOMMENDATIONS_DB", rec_db)
    monkeypatch.setattr(review_cli, "OUTCOMES_DB", out_db)
    monkeypatch.setattr(review_cli, "CHECKPOINTS_DB", ckpt_db)

    sent = {"telegram": [], "desktop": []}
    monkeypatch.setattr(review_cli, "send_telegram_message", lambda message: sent["telegram"].append(message) or True)
    monkeypatch.setattr(review_cli, "send_desktop_notification", lambda title, msg: sent["desktop"].append((title, msg)) or True)
    return rec_db, out_db, ckpt_db, sent


def _run_real_graph_to_pending(rec_db, ckpt_db, ticker="AAPL", as_of_date="2026-08-26"):
    source = YFinanceSource()
    bars = source.get_ohlcv(ticker, lookback_days=300)
    proxy_bars = source.get_ohlcv("SPY", lookback_days=300)
    llm = FakeLLM(responses=[RATIONALE_RESPONSE] * 10)

    conn = sqlite3.connect(ckpt_db, check_same_thread=False)
    from langgraph.checkpoint.sqlite import SqliteSaver
    from agents.schemas import SupervisorVerdict

    checkpointer = SqliteSaver(conn)
    final_state = run_for_ticker(
        ticker, AssetClass.US_EQUITY, bars, proxy_bars, equity=100_000,
        as_of_date=as_of_date, checkpointer=checkpointer, llm=llm,
    )
    conn.close()
    verdict = SupervisorVerdict.model_validate(final_state["supervisor_verdict"])
    save_recommendation(rec_db, verdict)
    return verdict.recommendation_id


@pytest.mark.network
def test_decide_approve_resumes_records_decision_and_sends_alert(cli_env):
    rec_db, out_db, ckpt_db, sent = cli_env
    recommendation_id = _run_real_graph_to_pending(rec_db, ckpt_db)

    exit_code = review_cli._decide(recommendation_id, "approved")

    assert exit_code == 0
    assert get_recommendation(rec_db, recommendation_id)["human_decision"] == "approved"
    assert len(sent["telegram"]) == 1
    assert len(sent["desktop"]) == 1


@pytest.mark.network
def test_decide_reject_records_decision_and_sends_no_alert(cli_env):
    rec_db, out_db, ckpt_db, sent = cli_env
    recommendation_id = _run_real_graph_to_pending(rec_db, ckpt_db, as_of_date="2026-08-27")

    exit_code = review_cli._decide(recommendation_id, "rejected")

    assert exit_code == 0
    assert get_recommendation(rec_db, recommendation_id)["human_decision"] == "rejected"
    assert sent["telegram"] == []
    assert sent["desktop"] == []


def test_decide_missing_recommendation_returns_error(cli_env):
    assert review_cli._decide("NOPE-2026-01-01", "approved") == 1


def test_decide_already_decided_refuses_second_resume(cli_env):
    rec_db, out_db, ckpt_db, sent = cli_env
    save_recommendation(rec_db, FIXTURE_VERDICT)
    update_human_decision(rec_db, FIXTURE_VERDICT.recommendation_id, "approved")

    assert review_cli._decide(FIXTURE_VERDICT.recommendation_id, "rejected") == 1
    assert get_recommendation(rec_db, FIXTURE_VERDICT.recommendation_id)["human_decision"] == "approved"


def test_log_outcome_requires_prior_approval(cli_env):
    rec_db, out_db, ckpt_db, sent = cli_env
    save_recommendation(rec_db, FIXTURE_VERDICT)  # human_decision still None -- never approved

    args = argparse.Namespace(
        ticker="AAPL", date="2026-08-26", actual_entry_price=300.0, actual_exit_price=311.0,
        exit_date="2026-09-02", exit_reason="target_hit", human_action="followed", realized_pnl=11.0,
    )
    assert review_cli._log_outcome(args) == 1
    assert get_outcome(out_db, "AAPL-2026-08-26") is None


def test_log_outcome_success_after_approval(cli_env):
    rec_db, out_db, ckpt_db, sent = cli_env
    save_recommendation(rec_db, FIXTURE_VERDICT)
    update_human_decision(rec_db, FIXTURE_VERDICT.recommendation_id, "approved")

    args = argparse.Namespace(
        ticker="AAPL", date="2026-08-26", actual_entry_price=300.0, actual_exit_price=311.0,
        exit_date="2026-09-02", exit_reason="target_hit", human_action="followed", realized_pnl=11.0,
    )
    assert review_cli._log_outcome(args) == 0
    outcome = get_outcome(out_db, "AAPL-2026-08-26")
    assert outcome["realized_pnl"] == 11.0


def test_pending_outcomes_prints_nothing_when_none_pending(cli_env, capsys):
    args = argparse.Namespace(older_than=90)
    assert review_cli._pending_outcomes(args) == 0
    assert "No approved recommendations" in capsys.readouterr().out
