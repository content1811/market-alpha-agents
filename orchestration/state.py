"""LangGraph state definition for the specialist-agent pipeline, per
docs/plan/section_orchestration.md section 4.

Crypto asset-class wiring: orchestration/graph.py now includes
crypto_derivatives_node and crypto_on_chain_node alongside the equity nodes --
every node runs for every ticker regardless of asset class (per this graph's
own stated design principle: "applicability is enforced INSIDE each node...
not by varying the graph's topology"), so short_squeeze_node no-ops for
AssetClass.CRYPTO (ShortSqueezeAgent.build_verdict raises for crypto by
design -- the node must never call it for a crypto ticker) and the two crypto
nodes no-op for anything that isn't AssetClass.CRYPTO. The crypto-specific
inputs below are fetched by the CALLER before building the initial state
(mirroring how `bars`/`proxy_bars` already work) -- see
data/connectors/crypto_derivatives_live.py and data/onchain_fetch.py.
"""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class PipelineState(TypedDict):
    ticker: str
    asset_class: str  # AssetClass.value -- "us_equity" | "jp_equity" | "crypto"
    as_of_date: str
    equity: float
    bars: list[dict]  # NormalizedBar.model_dump() dicts -- serializable for checkpointing
    proxy_bars: list[dict]
    prev_close: float | None  # JP tickers only, for RiskManagerAgent rule 9
    regime_multiplier: float
    crypto_funding_rate_history: list[float] | None  # CryptoDerivativesAgent input, crypto tickers only
    crypto_current_oi: float | None
    crypto_prior_oi: float | None
    crypto_onchain_inputs: dict | None  # CryptoOnChainAgent's build_verdict kwargs (mvrv/sopr_score/flow_score/whale_score/addr_divergence_score/unlock_penalty), crypto tickers only
    verdicts: Annotated[list[dict], operator.add]  # each specialist node appends its AgentVerdict dict
    risk_verdict: dict | None
    supervisor_verdict: dict | None
    human_decision: str | None  # set only by ui/review_cli.py resuming the approval_gate interrupt(); "approved" | "rejected"
