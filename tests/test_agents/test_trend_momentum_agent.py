"""Agent-level tests for TrendMomentumAgent -- mirrors
test_mean_reversion_agent.py's coverage of the same design principles.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from agents.trend_momentum_agent import build_verdict
from data.schema import AssetClass, NormalizedBar
from tests.test_agents.test_mean_reversion_agent import FakeLLM


def _synthetic_bars(n: int, drift: float, seed: int) -> list[NormalizedBar]:
    rng = np.random.RandomState(seed)
    closes = 100 * np.cumprod(1 + rng.normal(drift, 0.008, n))
    now = datetime.now(timezone.utc)
    return [
        NormalizedBar(
            symbol="FAKE",
            asset_class=AssetClass.US_EQUITY,
            ts_utc=now,
            open=float(c),
            high=float(c) * 1.005,
            low=float(c) * 0.995,
            close=float(c),
            volume=1_000_000.0,
            adjusted=True,
            source="synthetic",
            ingested_at=now,
        )
        for c in closes
    ]


def test_trend_momentum_agent_end_to_end_with_fake_llm():
    bars = _synthetic_bars(300, drift=0.001, seed=11)
    proxy_bars = _synthetic_bars(300, drift=0.0003, seed=12)
    llm = FakeLLM(responses=['{"rationale": "ADX moderate, trend gate open, MA spread positive, no chasing risk."}'])

    verdict = build_verdict("FAKE", AssetClass.US_EQUITY, bars, proxy_bars, llm=llm)

    assert -1.0 <= verdict.signal_score <= 1.0
    assert 0.0 <= verdict.confidence <= 1.0
    assert verdict.agent_name == "TrendMomentumAgent"
    assert "ADX" in verdict.rationale


def test_trend_momentum_agent_requires_bars():
    with pytest.raises(ValueError):
        build_verdict("FAKE", AssetClass.US_EQUITY, [], [], llm=FakeLLM(responses=[]))
