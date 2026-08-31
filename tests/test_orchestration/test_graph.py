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
from orchestration.graph import build_graph, resume_for_ticker, run_for_ticker
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


@pytest.mark.network
def test_graph_runs_crypto_ticker_with_squeeze_skipped_and_derivatives_onchain_active():
    from data.connectors.crypto_ccxt import CCXTSource
    from data.connectors.crypto_derivatives_live import fetch_derivatives_inputs
    from data.schema import AssetClass

    source = CCXTSource()
    bars = source.get_ohlcv("BTC/USDT", lookback_days=300)
    proxy_bars = bars  # BTC is its own market-regime proxy per market_regime_agent.py

    derivatives_inputs = fetch_derivatives_inputs("BTC/USDT")
    onchain_inputs = {
        "mvrv": None, "sopr_score": None, "flow_score": None,
        "whale_score": None, "addr_divergence_score": None, "unlock_penalty": 0.0,
    }
    llm = FakeLLM(responses=[RATIONALE_RESPONSE] * 10)

    final_state = run_for_ticker(
        "BTC/USDT", AssetClass.CRYPTO, bars, proxy_bars, equity=100_000, as_of_date="2026-08-26",
        llm=llm, crypto_funding_rate_history=derivatives_inputs["funding_rate_history"],
        crypto_current_oi=derivatives_inputs["current_oi"], crypto_prior_oi=derivatives_inputs["prior_oi"],
        crypto_onchain_inputs=onchain_inputs,
    )

    agent_names = {v["agent_name"] for v in final_state["verdicts"]}
    assert "ShortSqueezeAgent" not in agent_names
    assert "CryptoDerivativesAgent" in agent_names
    assert "CryptoOnChainAgent" in agent_names
    assert final_state["supervisor_verdict"]["asset_class"] == "crypto"


def test_graph_equity_ticker_still_skips_crypto_nodes():
    """No live call needed -- crypto nodes must no-op purely from
    asset_class/missing-inputs, without ever touching a crypto connector for
    an equity ticker."""
    from data.schema import AssetClass, NormalizedBar
    from datetime import datetime, timezone

    bars = [
        NormalizedBar(
            symbol="AAPL", asset_class=AssetClass.US_EQUITY, ts_utc=datetime.now(timezone.utc),
            open=price, high=price + 1.0, low=price - 1.0, close=price, volume=1_000_000.0, adjusted=True,
            source="fake", ingested_at=datetime.now(timezone.utc),
        )
        for i in range(300)
        for price in [100.0 + (i % 11) - (i % 5)]  # deterministic non-zero variance, avoids a std=0 NaN
    ]
    llm = FakeLLM(responses=[RATIONALE_RESPONSE] * 10)

    final_state = run_for_ticker("AAPL", AssetClass.US_EQUITY, bars, bars, equity=100_000, as_of_date="2026-08-26", llm=llm)

    agent_names = {v["agent_name"] for v in final_state["verdicts"]}
    assert "CryptoDerivativesAgent" not in agent_names
    assert "CryptoOnChainAgent" not in agent_names


def test_graph_has_no_edge_from_supervisor_directly_to_end():
    """The single most important regression test in this system, per
    docs/plan/section_orchestration.md section 3 Phase 7: no recommendation
    may ever reach END (and therefore be eligible for alerting/) without
    passing through approval_gate's interrupt() first. Asserted structurally
    against the compiled graph's own edge list, not just by convention."""
    app = build_graph().compile()
    edges = {(edge.source, edge.target) for edge in app.get_graph().edges}

    assert ("supervisor", "__end__") not in edges
    assert ("supervisor", "approval_gate") in edges
    assert ("approval_gate", "__end__") in edges


@pytest.mark.network
def test_graph_pauses_at_approval_gate_until_resumed():
    import sqlite3
    import tempfile
    from pathlib import Path

    from langgraph.checkpoint.sqlite import SqliteSaver

    from data.schema import AssetClass

    source = YFinanceSource()
    bars = source.get_ohlcv("AAPL", lookback_days=300)
    proxy_bars = source.get_ohlcv("SPY", lookback_days=300)
    llm = FakeLLM(responses=[RATIONALE_RESPONSE] * 10)

    with tempfile.TemporaryDirectory() as tmpdir:
        conn = sqlite3.connect(str(Path(tmpdir) / "checkpoints.db"), check_same_thread=False)
        checkpointer = SqliteSaver(conn)

        first_pass = run_for_ticker(
            "AAPL", AssetClass.US_EQUITY, bars, proxy_bars, equity=100_000,
            as_of_date="2026-08-26", checkpointer=checkpointer, llm=llm,
        )
        assert "__interrupt__" in first_pass
        assert first_pass["human_decision"] is None
        assert first_pass["supervisor_verdict"] is not None  # already written before the pause

        resumed = resume_for_ticker("AAPL-2026-08-26", "approved", checkpointer, llm=llm)
        assert "__interrupt__" not in resumed
        assert resumed["human_decision"] == "approved"
