"""LangGraph state definition for the equity specialist-agent pipeline, per
docs/plan/section_orchestration.md section 4.

Scope note: crypto asset-class wiring (CryptoOnChainAgent, CryptoDerivativesAgent
nodes) is not included in graph.py yet -- CryptoOnChainAgent itself is deferred
(blocked on the Dune/CryptoQuant connector, see README "Where things stand"),
and CryptoDerivativesAgent needs a funding-rate/OI fetch step this state
doesn't carry yet. This graph currently wires the US/JP equity path, which is
also the one fully live-verified end-to-end (see agents/ live-run commits).
"""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class PipelineState(TypedDict):
    ticker: str
    asset_class: str  # AssetClass.value -- "us_equity" | "jp_equity"
    as_of_date: str
    equity: float
    bars: list[dict]  # NormalizedBar.model_dump() dicts -- serializable for checkpointing
    proxy_bars: list[dict]
    prev_close: float | None  # JP tickers only, for RiskManagerAgent rule 9
    regime_multiplier: float
    verdicts: Annotated[list[dict], operator.add]  # each specialist node appends its AgentVerdict dict
    risk_verdict: dict | None
    supervisor_verdict: dict | None
