"""Live smoke tests against Alternative.me's Fear & Greed Index -- free and
keyless, so (per this project's precedent for keyless sources, e.g.
test_crypto_etherscan.py) tested live rather than mocked.
"""
from __future__ import annotations

import pytest

from data.connectors.alternative_me import get_fear_greed


@pytest.mark.network
def test_get_fear_greed_default_limit_returns_one_reading():
    readings = get_fear_greed()
    assert len(readings) == 1


@pytest.mark.network
def test_get_fear_greed_shape_and_value_range():
    readings = get_fear_greed(limit=3)
    assert len(readings) == 3
    for reading in readings:
        assert set(reading.keys()) == {"value", "value_classification", "timestamp"}
        assert isinstance(reading["value"], int)
        assert 0 <= reading["value"] <= 100
        assert isinstance(reading["value_classification"], str) and reading["value_classification"]
        assert isinstance(reading["timestamp"], int)


@pytest.mark.network
def test_get_fear_greed_ordered_newest_first():
    readings = get_fear_greed(limit=3)
    timestamps = [r["timestamp"] for r in readings]
    assert timestamps == sorted(timestamps, reverse=True)
