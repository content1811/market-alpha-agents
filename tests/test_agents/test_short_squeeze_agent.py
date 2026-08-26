"""Agent-level tests for ShortSqueezeAgent."""
from __future__ import annotations

import pytest

from agents.short_squeeze_agent import build_verdict
from data.schema import AssetClass
from signals.squeeze import OptionRow
from tests.test_agents.test_mean_reversion_agent import FakeLLM

UNUSUAL_ROWS = [OptionRow(strike=100, last_price=5.5, bid=5.0, ask=5.2, volume=600, open_interest=200)]


def test_short_squeeze_agent_degraded_mode_with_only_options_data():
    llm = FakeLLM(responses=['{"rationale": "SI/DTC/fee/util unavailable, options-only read, low confidence, no trigger."}'])

    verdict = build_verdict("FAKE", AssetClass.US_EQUITY, option_rows=UNUSUAL_ROWS, llm=llm)

    assert verdict.signal_score == pytest.approx(1.0)  # options_score=1.0, renormalized
    assert verdict.confidence == pytest.approx(0.15)
    assert "degraded" in (verdict.regime_gate_applied or "")


def test_short_squeeze_agent_full_data():
    llm = FakeLLM(responses=['{"rationale": "SI 20%, DTC 6d, fee 10%, util 95%, plus unusual options -- elevated squeeze setup."}'])

    verdict = build_verdict(
        "FAKE",
        AssetClass.US_EQUITY,
        si_pct_of_float=20,
        days_to_cover=6,
        borrow_fee_rate_pct=10,
        utilization_pct=95,
        option_rows=UNUSUAL_ROWS,
        llm=llm,
    )
    assert verdict.signal_score == pytest.approx(0.5325)
    assert verdict.regime_gate_applied is None


def test_short_squeeze_agent_rejects_crypto():
    with pytest.raises(ValueError):
        build_verdict("BTC/USDT", AssetClass.CRYPTO, llm=FakeLLM(responses=[]))
