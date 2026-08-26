"""Integration test for orchestration/graph.py -- the real LangGraph pipeline,
not just manual function composition. Uses real live OHLCV/options data (so
short_squeeze's yfinance call and risk_manager's ATR calc are realistic) but
a FakeLLM shared across all specialist nodes, since every node here uses the
same {"rationale": str} response shape -- which concurrent node consumes which
canned response doesn't matter for this test, only that the pipeline
completes and produces a valid, internally-consistent SupervisorVerdict.
"""
from __future__ import annotations

import json

import pytest

from data.connectors.us_equities_yfinance import YFinanceSource
from orchestration.graph import build_graph, run_for_ticker
from tests.test_agents.test_mean_reversion_agent import FakeLLM

RATIONALE_RESPONSE = json.dumps({"rationale": "Test rationale citing the computed numbers, under any length limit."})


@pytest.mark.network
def test_graph_runs_end_to_end_and_produces_valid_supervisor_verdict():
    source = YFinanceSource()
    bars = source.get_ohlcv("AAPL", lookback_days=300)
    proxy_bars = source.get_ohlcv("SPY", lookback_days=300)

    llm = FakeLLM(responses=[RATIONALE_RESPONSE] * 10)  # 6 nodes call it; headroom for scheduling order

    final_state = run_for_ticker(
        "AAPL", __import__("data.schema", fromlist=["AssetClass"]).AssetClass.US_EQUITY,
        bars, proxy_bars, equity=100_000, as_of_date="2026-08-26", llm=llm,
    )

    assert len(final_state["verdicts"]) == 6  # 5 specialists + news_sentiment (no-op, still appends)
    assert final_state["risk_verdict"] is not None
    assert final_state["supervisor_verdict"] is not None
    supervisor = final_state["supervisor_verdict"]
    assert supervisor["final_call"] in ("BUY", "SELL", "HOLD", "WATCH")
    assert supervisor["recommendation_id"] == "AAPL-2026-08-26"


@pytest.mark.network
def test_graph_checkpoints_and_resumes():
    import sqlite3
    import tempfile
    from pathlib import Path

    from langgraph.checkpoint.sqlite import SqliteSaver

    source = YFinanceSource()
    bars = source.get_ohlcv("AAPL", lookback_days=300)
    proxy_bars = source.get_ohlcv("SPY", lookback_days=300)
    llm = FakeLLM(responses=[RATIONALE_RESPONSE] * 10)

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "checkpoints.db"
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        saver = SqliteSaver(conn)

        from data.schema import AssetClass

        run_for_ticker(
            "AAPL", AssetClass.US_EQUITY, bars, proxy_bars, equity=100_000,
            as_of_date="2026-08-26", checkpointer=saver, llm=llm,
        )

        checkpoints = list(saver.list({"configurable": {"thread_id": "AAPL-2026-08-26"}}))
        assert len(checkpoints) > 0

        # simulate a fresh process resuming from the same checkpoint db
        conn2 = sqlite3.connect(str(db_path), check_same_thread=False)
        saver2 = SqliteSaver(conn2)
        resumed_checkpoints = list(saver2.list({"configurable": {"thread_id": "AAPL-2026-08-26"}}))
        assert len(resumed_checkpoints) == len(checkpoints)
        latest_state = resumed_checkpoints[0].checkpoint["channel_values"]
        assert latest_state.get("supervisor_verdict") is not None
