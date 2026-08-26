"""Agent-level tests for CryptoDerivativesAgent."""
from __future__ import annotations

import pytest

from agents.crypto_derivatives_agent import build_verdict
from tests.test_agents.test_mean_reversion_agent import FakeLLM


def test_crypto_derivatives_agent_end_to_end_with_fake_llm():
    llm = FakeLLM(responses=['{"rationale": "Funding modest, contrarian score mild, OI confirms uptrend, no squeeze flag."}'])

    verdict = build_verdict(
        "BTC/USDT",
        funding_rate_history=[0.0001, 0.00012, 0.00009, 0.0001, 0.00015],
        current_price=110.0,
        prior_price=100.0,
        current_oi=1000.0,
        prior_oi=900.0,
        llm=llm,
    )

    assert -1.0 <= verdict.signal_score <= 1.0
    assert verdict.agent_name == "CryptoDerivativesAgent"
    assert verdict.sub_scores["oi_score"] == pytest.approx(1.0)


def test_crypto_derivatives_agent_requires_funding_history():
    with pytest.raises(ValueError):
        build_verdict("BTC/USDT", [], 100.0, 100.0, 1000.0, 1000.0, llm=FakeLLM(responses=[]))
