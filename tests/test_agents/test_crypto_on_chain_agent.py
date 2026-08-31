"""Agent-level tests for CryptoOnChainAgent."""
from __future__ import annotations

import pytest

from agents.crypto_on_chain_agent import build_verdict
from tests.test_agents.test_mean_reversion_agent import FakeLLM


def test_crypto_on_chain_agent_end_to_end_with_fake_llm():
    llm = FakeLLM(
        responses=['{"rationale": "No free MVRV/SOPR source; Dune-approximated address trend only. Widely dashboarded, may already be priced in."}']
    )

    verdict = build_verdict("BTC/USDT", mvrv=1.5, unlock_penalty=0.0, llm=llm)

    assert -1.0 <= verdict.signal_score <= 1.0
    assert verdict.agent_name == "CryptoOnChainAgent"
    assert verdict.sub_scores["mvrv_score"] == pytest.approx(70.0)


def test_crypto_on_chain_agent_all_excluded_still_returns_a_verdict():
    llm = FakeLLM(responses=['{"rationale": "All indicators excluded -- no free MVRV/SOPR source, no local ledger history yet. Priced in elsewhere already."}'])

    verdict = build_verdict("ETH/USDT", llm=llm)

    assert verdict.signal_score == pytest.approx(0.0)
    assert verdict.confidence == pytest.approx(0.06)  # only unlock_penalty (weight 0.10) counted
    assert verdict.regime_gate_applied == "excluded=mvrv,sopr,flow,whale,addr_divergence"
