"""Agent-level tests for MeanReversionAgent, per the Phase 2 test mandate in
docs/plan/section_orchestration.md section 3: the LLM call always returns
schema-valid JSON (retry-with-repair on validation failure), and signal_score/
confidence are genuinely independent of the LLM (never LLM-settable at all,
by construction -- see RationaleOutput's schema).
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from agents.mean_reversion_agent import build_verdict
from data.schema import AssetClass, DataQualityFlag, NormalizedBar
from signals.ta.mean_reversion import compute_mean_reversion


class FakeAIMessage:
    def __init__(self, content: str):
        self.content = content


class FakeLLM:
    """Stands in for a langchain chat model: returns each of `responses` in
    order on successive .invoke() calls, so retry-with-repair can be tested
    without a network call."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.call_count = 0

    def invoke(self, messages):
        response = self._responses[self.call_count]
        self.call_count += 1
        return FakeAIMessage(response)


def _synthetic_bars(n: int = 250, seed: int = 5) -> list[NormalizedBar]:
    rng = np.random.RandomState(seed)
    closes = 100 + np.sin(np.arange(n) / 5) * 3 + rng.normal(0, 0.3, n)
    now = datetime.now(timezone.utc)
    return [
        NormalizedBar(
            symbol="FAKE",
            asset_class=AssetClass.US_EQUITY,
            ts_utc=now,
            open=float(c),
            high=float(c) + 0.2,
            low=float(c) - 0.2,
            close=float(c),
            volume=1_000_000.0,
            adjusted=True,
            source="synthetic",
            ingested_at=now,
        )
        for c in closes
    ]


def test_retry_with_repair_recovers_from_invalid_json():
    bars = _synthetic_bars()
    llm = FakeLLM(responses=["not json at all", '{"rationale": "ADX 12, gate open. z-score mild. Target mid-band."}'])

    verdict = build_verdict("FAKE", AssetClass.US_EQUITY, bars, llm=llm)

    assert llm.call_count == 2  # first attempt failed, repair attempt succeeded
    assert "ADX 12" in verdict.rationale


def test_exhausting_repair_attempts_raises():
    from agents.llm_client import LLMCallError

    bars = _synthetic_bars()
    llm = FakeLLM(responses=["still not json", "still not json either"])

    with pytest.raises(LLMCallError):
        build_verdict("FAKE", AssetClass.US_EQUITY, bars, llm=llm)


def test_signal_score_and_confidence_are_not_llm_settable():
    """The LLM's response schema (RationaleOutput) has no score/confidence
    field at all -- this test proves the resulting AgentVerdict's numeric
    fields match the deterministic signals module exactly, regardless of
    what free text the LLM returns."""
    bars = _synthetic_bars()
    df = pd.DataFrame([b.model_dump() for b in bars]).sort_values("ts_utc")
    expected = compute_mean_reversion(df["high"], df["low"], df["close"])

    llm = FakeLLM(responses=['{"rationale": "some rationale under 280 chars, citing ADX and z-score numbers here."}'])
    verdict = build_verdict("FAKE", AssetClass.US_EQUITY, bars, llm=llm)

    assert verdict.signal_score == pytest.approx(expected.signal_score)
    assert verdict.confidence == pytest.approx(expected.confidence)


def test_stale_data_quality_flag_caps_confidence():
    bars = _synthetic_bars()
    bars[-1] = bars[-1].model_copy(update={"data_quality_flag": DataQualityFlag.STALE})
    llm = FakeLLM(responses=['{"rationale": "ADX moderate, gate partially open, citing z-score and RSI2."}'])

    verdict = build_verdict("FAKE", AssetClass.US_EQUITY, bars, llm=llm)

    # canonical rule, section_data_pipeline.md section 2.4: stale caps confidence <= 0.3
    assert verdict.confidence <= 0.3
    assert verdict.data_quality_flag == DataQualityFlag.STALE
