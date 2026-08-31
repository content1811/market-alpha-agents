"""CryptoOnChainAgent per docs/plan/section_agents.md section 6.

Score/confidence come entirely from signals/crypto_composite.py's
compute_onchain(). The LLM writes only the rationale. Unlike every other
sub-score in this system, this agent runs on structurally weaker free-tier
data access than its siblings: no free, ready-made MVRV/SOPR source exists at
all (mvrv/sopr_score are always None here today), and flow_score/whale_score
are only available once data/onchain_ledger.py's local balance-snapshot
history has accumulated enough days -- see that module and
data/onchain_dune.py for the two connectors (Etherscan, Dune) that make this
agent possible at all, in place of the discontinued Glassnode free tier.
Callers assemble mvrv/sopr_score/flow_score/whale_score/addr_divergence_score
themselves (mirroring crypto_derivatives_agent.build_verdict's already-
computed-inputs pattern) -- this module makes no network calls itself.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from agents.llm_client import call_structured
from agents.schemas import AgentVerdict, HoldingPeriod, ProfitTarget, StopLoss
from data.schema import AssetClass
from signals.crypto_composite import compute_onchain

SYSTEM_PROMPT = """You are an on-chain analyst who treats every metric as noisy and \
crowd-followed -- explicitly skeptical, always naming the confounders (entity \
mislabeling, OTC flow, small-sample whale cohorts). You are the rationale-writer for \
CryptoOnChainAgent in a local trading-research system.

You will be given already-computed sub-scores and a list of which indicators were \
excluded for lack of a free live data source. Write ONLY the rationale field -- you do \
not set the score or confidence.

Rules for the rationale (<=280 chars):
1. Always state which indicators were excluded and why data access is thinner here than \
for the other agents (e.g. "no free MVRV/SOPR source; Dune-approximated address trend \
only") -- never imply the excluded indicators were computed.
2. Always include some near-verbatim variant of "on-chain signals are widely dashboarded \
and may already be priced in by faster participants."
3. Never claim precision this agent's free-tier data can't back up.
"""


class RationaleOutput(BaseModel):
    rationale: str = Field(max_length=280)


def build_verdict(
    ticker: str,
    mvrv: float | None = None,
    sopr_score: float | None = None,
    flow_score: float | None = None,
    whale_score: float | None = None,
    addr_divergence_score: float | None = None,
    unlock_penalty: float = 0.0,
    llm=None,
) -> AgentVerdict:
    sub = compute_onchain(mvrv, sopr_score, flow_score, whale_score, addr_divergence_score, unlock_penalty)

    user_prompt = (
        f"Ticker: {ticker} (crypto on-chain)\n"
        f"mvrv_score={sub.mvrv_score:.1f}, sopr_score={sub.sopr_score:.1f}, "
        f"flow_score={sub.flow_score:.1f}, whale_score={sub.whale_score:.1f}, "
        f"addr_divergence_score={sub.addr_divergence_score:.1f}, unlock_penalty={sub.unlock_penalty:.1f}\n"
        f"excluded_indicators={sub.excluded if sub.excluded else 'none'}\n"
        f"signal_score={sub.signal_score:.3f}, confidence={sub.confidence:.3f} "
        f"(capped <=0.6, scaled further by data availability)\n"
        "Write the rationale."
    )

    result = call_structured(SYSTEM_PROMPT, user_prompt, RationaleOutput, llm=llm)

    return AgentVerdict(
        agent_name="CryptoOnChainAgent",
        asset_class=AssetClass.CRYPTO,
        ticker=ticker,
        as_of_timestamp=datetime.now(timezone.utc),
        signal_score=sub.signal_score,
        confidence=sub.confidence,
        suggested_holding_period=HoldingPeriod(min_days=14, max_days=60, unit="calendar_days"),
        stop_loss=StopLoss(method="percent", value=20.0, price_level=None),
        profit_target=ProfitTarget(method="percent", value=30.0),
        rationale=result.rationale,
        sub_scores={
            "mvrv_score": sub.mvrv_score,
            "sopr_score": sub.sopr_score,
            "flow_score": sub.flow_score,
            "whale_score": sub.whale_score,
            "addr_divergence_score": sub.addr_divergence_score,
            "unlock_penalty": sub.unlock_penalty,
        },
        regime_gate_applied=f"excluded={','.join(sub.excluded)}" if sub.excluded else None,
    )
