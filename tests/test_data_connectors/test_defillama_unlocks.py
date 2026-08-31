"""Tests for data/connectors/defillama_unlocks.py. Not configured in this
environment (no DEFILLAMA_API_KEY registered -- DefiLlama's unlock calendar
turned out to be Pro-API-only/paid, not free as originally assumed; see the
module's docstring for the live verification). Two network tests confirm
that verified finding stays true (the free-tier path 402s, not a 200 this
parser could silently mis-read); the rest mock the HTTP layer to cover the
parsing logic, same precedent as alerting/telegram_bot.py mock-testing a
channel with no real credentials available.
"""
from __future__ import annotations

import pytest
import requests

from data.connectors.defillama_unlocks import (
    DefiLlamaSettings,
    DefiLlamaUnlocksSource,
    get_upcoming_unlocks,
)

MOCK_EMISSIONS_LIST = [
    {
        "token": "coingecko:whitebit",
        "name": "WhiteBIT",
        "gecko_id": "whitebit",
        "circSupply": 1_000_000,
        "maxSupply": 2_000_000,
        "mcap": 5_000_000,
        "events": [
            {
                "timestamp": None,  # placeholder, overwritten per-test
                "noOfTokens": [50_000],
                "category": "insiders",
                "unlockType": "cliff",
                "description": "test event",
            }
        ],
    }
]


@pytest.mark.network
def test_free_tier_emissions_endpoint_confirmed_paid_2026_08_31():
    """Locks in the live-verified finding: the old free /emissions path is
    not free anymore -- it 402s with a paid-plan-upgrade message, not a 200
    a naive parser might have mis-read as an empty/valid unlock list."""
    response = requests.get("https://api.llama.fi/emissions", timeout=15)
    assert response.status_code == 402
    assert "paid" in response.text.lower()


@pytest.mark.network
def test_free_tier_unlocks_path_confirmed_404_2026_08_31():
    response = requests.get("https://api.llama.fi/unlocks", timeout=15)
    assert response.status_code == 404


def test_source_construction_raises_when_key_missing():
    with pytest.raises(ValueError, match="DEFILLAMA_API_KEY"):
        DefiLlamaUnlocksSource(DefiLlamaSettings(defillama_api_key=None))


def test_get_upcoming_unlocks_filters_by_symbol_and_window(monkeypatch):
    import time

    now = time.time()
    in_window_ts = now + 10 * 86400  # 10 days out
    out_of_window_ts = now + 45 * 86400  # 45 days out, outside a 30d window

    mock_payload = [
        {
            "token": "coingecko:whitebit",
            "name": "WhiteBIT",
            "gecko_id": "whitebit",
            "circSupply": 1_000_000,
            "events": [
                {
                    "timestamp": in_window_ts,
                    "noOfTokens": [50_000],
                    "category": "insiders",
                    "unlockType": "cliff",
                },
                {
                    "timestamp": out_of_window_ts,
                    "noOfTokens": [999_999],
                    "category": "insiders",
                    "unlockType": "cliff",
                },
            ],
        },
        {
            "token": "coingecko:othertoken",
            "name": "OtherToken",
            "gecko_id": "othertoken",
            "circSupply": 500_000,
            "events": [{"timestamp": in_window_ts, "noOfTokens": [1_000], "category": "insiders", "unlockType": "cliff"}],
        },
    ]

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return mock_payload

    def fake_get(self, url, timeout):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr(requests.Session, "get", fake_get)

    settings = DefiLlamaSettings(defillama_api_key="TESTKEY")
    results = get_upcoming_unlocks("whitebit", within_days=30, settings=settings)

    assert "TESTKEY" in captured["url"]
    assert len(results) == 1  # the 45-day-out event is filtered out by within_days=30
    event = results[0]
    assert event["amount_usd_or_tokens"] == 50_000
    assert event["pct_of_circulating_supply"] == pytest.approx(5.0)  # 50_000 / 1_000_000 * 100
    assert event["category"] == "insiders"
    assert event["unlock_type"] == "cliff"


def test_get_upcoming_unlocks_returns_empty_when_symbol_not_found(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return MOCK_EMISSIONS_LIST

    monkeypatch.setattr(requests.Session, "get", lambda self, url, timeout: FakeResponse())

    settings = DefiLlamaSettings(defillama_api_key="TESTKEY")
    results = get_upcoming_unlocks("nonexistent-token-xyz", within_days=30, settings=settings)

    assert results == []
