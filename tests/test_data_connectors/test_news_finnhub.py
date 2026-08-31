"""Live smoke test for data/connectors/news_finnhub.py -- hits the real
Finnhub company-news endpoint per docs/research/news_alerts.md section 1.
"""
from __future__ import annotations

import pytest

from data.connectors.news_finnhub import fetch_finnhub_company_news


@pytest.mark.network
def test_fetch_finnhub_company_news_returns_sane_headlines():
    headlines = fetch_finnhub_company_news("AAPL")

    assert len(headlines) >= 1
    headline = headlines[0]
    assert set(headline.keys()) == {"title", "source", "hours_since", "item_id"}
    assert headline["title"]
    assert headline["source"]
    assert 0.0 <= headline["hours_since"] <= 72.0
    assert len(headline["item_id"]) == 16
