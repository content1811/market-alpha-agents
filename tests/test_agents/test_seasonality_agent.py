"""Agent-level tests for SeasonalityAgent."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from agents.seasonality_agent import build_verdict
from data.schema import AssetClass, NormalizedBar
from tests.test_agents.test_mean_reversion_agent import FakeLLM


def _synthetic_bars(n: int = 500, seed: int = 31) -> list[NormalizedBar]:
    rng = np.random.RandomState(seed)
    closes = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    now = datetime.now(timezone.utc)
    date_range = pd.date_range(end=pd.Timestamp(now).tz_localize(None), periods=n, freq="B")
    return [
        NormalizedBar(
            symbol="FAKE",
            asset_class=AssetClass.US_EQUITY,
            ts_utc=ts.tz_localize("UTC").to_pydatetime(),
            open=float(c),
            high=float(c) * 1.01,
            low=float(c) * 0.99,
            close=float(c),
            volume=1_000_000.0,
            adjusted=True,
            source="synthetic",
            ingested_at=now,
        )
        for c, ts in zip(closes, date_range)
    ]


def test_seasonality_agent_end_to_end_with_fake_llm():
    bars = _synthetic_bars()
    llm = FakeLLM(responses=['{"rationale": "n=80 turn-of-month, no significance test, thin contrarian tilt only."}'])

    verdict = build_verdict("FAKE", AssetClass.US_EQUITY, bars, llm=llm)

    assert abs(verdict.signal_score) <= 0.3
    assert verdict.confidence <= 0.5
    assert verdict.agent_name == "SeasonalityAgent"


def test_seasonality_agent_requires_bars():
    with pytest.raises(ValueError):
        build_verdict("FAKE", AssetClass.US_EQUITY, [], llm=FakeLLM(responses=[]))
