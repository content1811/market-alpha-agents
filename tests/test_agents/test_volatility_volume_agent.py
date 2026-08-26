"""Agent-level tests for VolatilityVolumeAgent."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from agents.volatility_volume_agent import build_verdict
from data.schema import AssetClass, NormalizedBar
from tests.test_agents.test_mean_reversion_agent import FakeLLM


def _synthetic_bars(n: int = 100, seed: int = 21) -> list[NormalizedBar]:
    rng = np.random.RandomState(seed)
    closes = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    volumes = rng.uniform(500_000, 1_000_000, n)
    now = datetime.now(timezone.utc)
    return [
        NormalizedBar(
            symbol="FAKE",
            asset_class=AssetClass.US_EQUITY,
            ts_utc=now,
            open=float(c),
            high=float(c) * 1.01,
            low=float(c) * 0.99,
            close=float(c),
            volume=float(v),
            adjusted=True,
            source="synthetic",
            ingested_at=now,
        )
        for c, v in zip(closes, volumes)
    ]


def test_volatility_volume_agent_end_to_end_with_fake_llm():
    bars = _synthetic_bars()
    llm = FakeLLM(responses=['{"rationale": "RVOL confirms, ATR14 cited, adequate volume for sizing."}'])

    verdict = build_verdict("FAKE", AssetClass.US_EQUITY, bars, llm=llm)

    assert -1.0 <= verdict.signal_score <= 1.0
    assert verdict.sub_scores["atr14"] > 0
    assert verdict.agent_name == "VolatilityVolumeAgent"


def test_volatility_volume_agent_requires_bars():
    with pytest.raises(ValueError):
        build_verdict("FAKE", AssetClass.US_EQUITY, [], llm=FakeLLM(responses=[]))
