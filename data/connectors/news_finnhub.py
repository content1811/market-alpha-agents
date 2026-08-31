"""Finnhub company-news adapter, keyed, per docs/research/news_alerts.md
section 1: RSS gives general-interest headlines only, whereas Finnhub's
`company-news` endpoint is ticker-scoped, closing the gap the module
docstring in agents/news_sentiment_agent.py flags for US equities.

Not a DataSource subclass -- this returns headline dicts, not OHLCV bars, so
the ABC in data/connectors/base.py (rate-limit ledger + cache keyed on
symbol/lookback_days bars) doesn't apply here.

Returns the same {"title", "source", "hours_since", "item_id"} shape
agents/news_sentiment_agent.py's fetch_headlines() already produces, using
its exact hashlib.sha256(url+title) item_id scheme, so the two sources can be
merged and de-duplicated directly.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import requests
from pydantic_settings import BaseSettings, SettingsConfigDict

FINNHUB_COMPANY_NEWS_URL = "https://finnhub.io/api/v1/company-news"


class FinnhubSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    finnhub_api_key: str | None = None


def fetch_finnhub_company_news(ticker: str, lookback_hours: int = 72) -> list[dict]:
    settings = FinnhubSettings()
    if not settings.finnhub_api_key:
        return []

    now = datetime.now(timezone.utc)
    params = {
        "symbol": ticker,
        "from": (now - timedelta(hours=lookback_hours)).date().isoformat(),
        "to": now.date().isoformat(),
        "token": settings.finnhub_api_key,
    }
    response = requests.get(FINNHUB_COMPANY_NEWS_URL, params=params, timeout=15)
    response.raise_for_status()

    headlines = []
    for article in response.json():
        published_dt = datetime.fromtimestamp(article["datetime"], tz=timezone.utc)
        hours_since = max(0.0, (now - published_dt).total_seconds() / 3600)
        # Finnhub's from/to are date-only, so the response can span more than
        # lookback_hours -- trim it down the same way fetch_headlines() does.
        if hours_since > lookback_hours:
            continue
        headlines.append(
            {
                "title": article["headline"],
                "source": article["source"],
                "hours_since": hours_since,
                "item_id": hashlib.sha256((article["url"] + article["headline"]).encode()).hexdigest()[:16],
            }
        )
    return headlines


if __name__ == "__main__":
    headlines = fetch_finnhub_company_news("AAPL")
    print(f"Fetched {len(headlines)} Finnhub headlines for AAPL")
    if headlines:
        print(headlines[0])
