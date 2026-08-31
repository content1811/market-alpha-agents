"""LangGraph orchestration graph for the specialist pipeline, per
docs/plan/section_orchestration.md sections 1 and 4.

One node per specialist -- applicability is enforced INSIDE each node (per
section_agents.md section 0's asset-class matrix), not by varying the graph's
topology, so a crypto ticker's node behaves the same way structurally as an
equity ticker's: short_squeeze_node no-ops for AssetClass.CRYPTO (that agent
raises for crypto by design -- see agents/short_squeeze_agent.py), and
crypto_derivatives_node/crypto_on_chain_node no-op for anything that isn't
crypto. `build_graph(llm=...)` takes an optional LLM override purely so tests
can inject a FakeLLM instead of hitting the real Rakuten gateway on every node.
"""
from __future__ import annotations

from datetime import date

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agents import (
    crypto_derivatives_agent,
    crypto_on_chain_agent,
    mean_reversion_agent,
    news_sentiment_agent,
    portfolio_supervisor_agent,
    seasonality_agent,
    short_squeeze_agent,
    trend_momentum_agent,
    volatility_volume_agent,
)
from agents.risk_manager_agent import build_verdict as risk_build_verdict
from data.schema import AssetClass, NormalizedBar
from orchestration.state import PipelineState
from signals.volatility_volume import compute_volatility_volume
import pandas as pd


def _bars_df(bars: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(bars).sort_values("ts_utc")


def _to_bars(raw: list[dict]) -> list[NormalizedBar]:
    return [NormalizedBar.model_validate(b) for b in raw]


def build_graph(llm=None, news_headlines: list[dict] | None = None):
    def mean_reversion_node(state: PipelineState) -> dict:
        v = mean_reversion_agent.build_verdict(state["ticker"], AssetClass(state["asset_class"]), _to_bars(state["bars"]), llm=llm)
        return {"verdicts": [v.model_dump(mode="json")]}

    def trend_momentum_node(state: PipelineState) -> dict:
        v = trend_momentum_agent.build_verdict(
            state["ticker"], AssetClass(state["asset_class"]), _to_bars(state["bars"]), _to_bars(state["proxy_bars"]), llm=llm
        )
        return {"verdicts": [v.model_dump(mode="json")]}

    def volatility_volume_node(state: PipelineState) -> dict:
        v = volatility_volume_agent.build_verdict(state["ticker"], AssetClass(state["asset_class"]), _to_bars(state["bars"]), llm=llm)
        return {"verdicts": [v.model_dump(mode="json")]}

    def seasonality_node(state: PipelineState) -> dict:
        v = seasonality_agent.build_verdict(state["ticker"], AssetClass(state["asset_class"]), _to_bars(state["bars"]), llm=llm)
        return {"verdicts": [v.model_dump(mode="json")]}

    def short_squeeze_node(state: PipelineState) -> dict:
        if AssetClass(state["asset_class"]) == AssetClass.CRYPTO:
            return {"verdicts": []}
        v = short_squeeze_agent.build_verdict(state["ticker"], AssetClass(state["asset_class"]), llm=llm)
        return {"verdicts": [v.model_dump(mode="json")]}

    def crypto_derivatives_node(state: PipelineState) -> dict:
        if AssetClass(state["asset_class"]) != AssetClass.CRYPTO or not state.get("crypto_funding_rate_history"):
            return {"verdicts": []}
        bars = _to_bars(state["bars"])
        v = crypto_derivatives_agent.build_verdict(
            state["ticker"],
            funding_rate_history=state["crypto_funding_rate_history"],
            current_price=bars[-1].close,
            prior_price=bars[-2].close,
            current_oi=state["crypto_current_oi"],
            prior_oi=state["crypto_prior_oi"],
            llm=llm,
        )
        return {"verdicts": [v.model_dump(mode="json")]}

    def crypto_on_chain_node(state: PipelineState) -> dict:
        if AssetClass(state["asset_class"]) != AssetClass.CRYPTO or state.get("crypto_onchain_inputs") is None:
            return {"verdicts": []}
        v = crypto_on_chain_agent.build_verdict(state["ticker"], **state["crypto_onchain_inputs"], llm=llm)
        return {"verdicts": [v.model_dump(mode="json")]}

    def news_sentiment_node(state: PipelineState) -> dict:
        v = news_sentiment_agent.build_verdict(
            state["ticker"], AssetClass(state["asset_class"]), headlines=news_headlines if news_headlines is not None else [], llm=llm
        )
        return {"verdicts": [v.model_dump(mode="json")]}

    def risk_manager_node(state: PipelineState) -> dict:
        df = _bars_df(state["bars"])
        vol_sub = compute_volatility_volume(df["high"], df["low"], df["close"], df["volume"])
        entry_price = float(df["close"].iloc[-1])
        risk = risk_build_verdict(
            equity=state["equity"],
            entry_price=entry_price,
            atr14=vol_sub.atr14,
            stop_multiple=2.0,
            asset_class=AssetClass(state["asset_class"]),
            regime_multiplier=state["regime_multiplier"],
            prev_close=state.get("prev_close"),
        )
        return {"risk_verdict": risk.model_dump(mode="json")}

    def supervisor_node(state: PipelineState) -> dict:
        from agents.schemas import AgentVerdict, RiskManagerVerdict

        verdicts = [AgentVerdict.model_validate(v) for v in state["verdicts"]]
        risk_verdict = RiskManagerVerdict.model_validate(state["risk_verdict"])
        supervisor = portfolio_supervisor_agent.build_verdict(
            state["ticker"],
            AssetClass(state["asset_class"]),
            verdicts,
            risk_verdict,
            as_of_date=state["as_of_date"],
            regime_multiplier=state["regime_multiplier"],
            llm=llm,
        )
        return {"supervisor_verdict": supervisor.model_dump(mode="json")}

    def approval_gate_node(state: PipelineState) -> dict:
        """The one and only node that can ever precede END, per
        docs/plan/section_orchestration.md section 3 Phase 7: "no recommendation
        is ever written to alerting/ without passing through the interrupt()/
        human-approval node." Every invoke() of this graph pauses HERE --
        callers (scripts/run_daily_scan.py) only ever see a state with
        supervisor_verdict populated but human_decision still None; only
        ui/review_cli.py's approve|reject flow resumes past this point via
        Command(resume="approved"|"rejected"), and only that resumed call is
        allowed to hand the verdict to alerting/."""
        decision = interrupt(
            {
                "recommendation_id": state["supervisor_verdict"]["recommendation_id"],
                "ticker": state["ticker"],
                "final_call": state["supervisor_verdict"]["final_call"],
                "blended_score": state["supervisor_verdict"]["blended_score"],
                "rationale": state["supervisor_verdict"]["rationale"],
            }
        )
        return {"human_decision": decision}

    graph = StateGraph(PipelineState)
    specialist_nodes = [
        "mean_reversion",
        "trend_momentum",
        "volatility_volume",
        "seasonality",
        "short_squeeze",
        "news_sentiment",
        "crypto_derivatives",
        "crypto_on_chain",
    ]
    graph.add_node("mean_reversion", mean_reversion_node)
    graph.add_node("trend_momentum", trend_momentum_node)
    graph.add_node("volatility_volume", volatility_volume_node)
    graph.add_node("seasonality", seasonality_node)
    graph.add_node("short_squeeze", short_squeeze_node)
    graph.add_node("news_sentiment", news_sentiment_node)
    graph.add_node("crypto_derivatives", crypto_derivatives_node)
    graph.add_node("crypto_on_chain", crypto_on_chain_node)
    graph.add_node("risk_manager", risk_manager_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("approval_gate", approval_gate_node)

    for node_name in specialist_nodes:
        graph.add_edge(START, node_name)
        graph.add_edge(node_name, "risk_manager")
    graph.add_edge("risk_manager", "supervisor")
    graph.add_edge("supervisor", "approval_gate")
    graph.add_edge("approval_gate", END)

    return graph


def run_for_ticker(
    ticker: str,
    asset_class: AssetClass,
    bars: list[NormalizedBar],
    proxy_bars: list[NormalizedBar],
    equity: float,
    as_of_date: str | None = None,
    regime_multiplier: float = 1.0,
    prev_close: float | None = None,
    checkpointer=None,
    llm=None,
    news_headlines: list[dict] | None = None,
    crypto_funding_rate_history: list[float] | None = None,
    crypto_current_oi: float | None = None,
    crypto_prior_oi: float | None = None,
    crypto_onchain_inputs: dict | None = None,
) -> dict:
    """Convenience entrypoint: builds the graph, runs it for one ticker, and
    returns the final state. `recommendation_id` (== thread_id) follows the
    f"{ticker}-{as_of_date}" convention used throughout Phase 6/7's outcome
    logging (see section_orchestration.md section 3 Phase 7). The crypto_*
    kwargs are ignored for non-crypto tickers (see crypto_derivatives_node/
    crypto_on_chain_node in build_graph) -- callers fetch them via
    data/connectors/crypto_derivatives_live.py and data/onchain_fetch.py
    before calling this, mirroring how bars/proxy_bars are already fetched
    by the caller rather than inside the graph."""
    as_of_date = as_of_date or date.today().isoformat()
    app = build_graph(llm=llm, news_headlines=news_headlines).compile(checkpointer=checkpointer)

    recommendation_id = f"{ticker}-{as_of_date}"
    config = {"configurable": {"thread_id": recommendation_id}} if checkpointer else {}

    initial_state: PipelineState = {
        "ticker": ticker,
        "asset_class": asset_class.value,
        "as_of_date": as_of_date,
        "equity": equity,
        "bars": [b.model_dump(mode="json") for b in bars],
        "proxy_bars": [b.model_dump(mode="json") for b in proxy_bars],
        "prev_close": prev_close,
        "regime_multiplier": regime_multiplier,
        "crypto_funding_rate_history": crypto_funding_rate_history,
        "crypto_current_oi": crypto_current_oi,
        "crypto_prior_oi": crypto_prior_oi,
        "crypto_onchain_inputs": crypto_onchain_inputs,
        "verdicts": [],
        "risk_verdict": None,
        "supervisor_verdict": None,
        "human_decision": None,
    }
    return app.invoke(initial_state, config)


def resume_for_ticker(
    recommendation_id: str,
    decision: str,
    checkpointer,
    llm=None,
    news_headlines: list[dict] | None = None,
) -> dict:
    """Resumes a graph paused at approval_gate_node (see build_graph), per
    ui/review_cli.py's approve|reject flow -- the only caller allowed to move
    a recommendation's human_decision away from None. `checkpointer` must be
    reconnected to the same orchestration/checkpoints.db the original
    scripts/run_daily_scan.py run used; `recommendation_id` doubles as the
    thread_id (see run_for_ticker)."""
    app = build_graph(llm=llm, news_headlines=news_headlines).compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": recommendation_id}}
    return app.invoke(Command(resume=decision), config)
