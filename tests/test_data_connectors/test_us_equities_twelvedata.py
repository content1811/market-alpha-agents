"""Adapter smoke test for the Twelve Data fallback/cross-check source, per
docs/plan/section_data_pipeline.md section 2.2's adapter-level test
requirement. Requires network access and a real TWELVEDATA_API_KEY (hits the
live api.twelvedata.com endpoint).
"""
from __future__ import annotations

import pytest

from data.connectors.us_equities_twelvedata import TwelveDataSource


@pytest.mark.network
def test_get_ohlcv_returns_sane_ascending_bars():
    source = TwelveDataSource()
    bars = source.get_ohlcv("AAPL", lookback_days=5)

    assert len(bars) >= 1
    for bar in bars:
        assert bar.symbol == "AAPL"
        assert bar.source == "twelvedata"
        assert bar.adjusted is True
        assert bar.low <= bar.open <= bar.high
        assert bar.low <= bar.close <= bar.high
        assert bar.volume > 0

    timestamps = [bar.ts_utc for bar in bars]
    assert timestamps == sorted(timestamps)
