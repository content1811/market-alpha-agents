"""Unit tests for data/news_db.py -- hand-constructed NormalizedNewsItem
fixtures, no network needed (that's covered by the RSS/Finnhub connector
tests in tests/test_data_connectors/).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from data.news_db import (
    get_news_items_for_symbol,
    save_news_item,
    save_sentiment_score,
)
from data.schema import NormalizedNewsItem

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "news.db")


def _item(item_id, symbol_tags, headline, published_at_utc, ingested_at=NOW) -> NormalizedNewsItem:
    return NormalizedNewsItem(
        item_id=item_id,
        symbol_tags=symbol_tags,
        headline=headline,
        summary=f"summary for {headline}",
        source="test-source",
        url=f"https://example.com/{item_id}",
        published_at_utc=published_at_utc,
        ingested_at=ingested_at,
    )


def test_save_and_get_roundtrip(db_path):
    item = _item("id-1", ["AAPL"], "Apple beats earnings", NOW - timedelta(hours=1))
    save_news_item(db_path, item)
    save_sentiment_score(db_path, "id-1", "finbert", sentiment=0.8, relevance=0.9)

    results = get_news_items_for_symbol(db_path, "AAPL", since_utc=NOW - timedelta(days=1))

    assert len(results) == 1
    row = results[0]
    assert row["item_id"] == "id-1"
    assert row["headline"] == "Apple beats earnings"
    assert row["source"] == "test-source"
    assert row["sentiment"] == pytest.approx(0.8)
    assert row["relevance"] == pytest.approx(0.9)
    assert row["source_agent"] == "finbert"


def test_upsert_by_item_id_overwrites_not_duplicates(db_path):
    item = _item("id-1", ["AAPL"], "Original headline", NOW - timedelta(hours=1))
    save_news_item(db_path, item)

    updated = _item("id-1", ["AAPL"], "Corrected headline", NOW - timedelta(hours=1))
    save_news_item(db_path, updated)

    results = get_news_items_for_symbol(db_path, "AAPL", since_utc=NOW - timedelta(days=1))
    assert len(results) == 1
    assert results[0]["headline"] == "Corrected headline"


def test_symbol_filter_excludes_non_matching_items(db_path):
    save_news_item(db_path, _item("id-1", ["AAPL"], "Apple news", NOW - timedelta(hours=1)))
    save_news_item(db_path, _item("id-2", ["MSFT"], "Microsoft news", NOW - timedelta(hours=1)))
    save_news_item(db_path, _item("id-3", ["AAPL", "MSFT"], "Both tagged", NOW - timedelta(hours=1)))

    results = get_news_items_for_symbol(db_path, "AAPL", since_utc=NOW - timedelta(days=1))
    ids = {row["item_id"] for row in results}

    assert ids == {"id-1", "id-3"}


def test_since_filter_excludes_older_items(db_path):
    save_news_item(db_path, _item("id-old", ["AAPL"], "Old news", NOW - timedelta(days=5)))
    save_news_item(db_path, _item("id-new", ["AAPL"], "Fresh news", NOW - timedelta(hours=1)))

    results = get_news_items_for_symbol(db_path, "AAPL", since_utc=NOW - timedelta(days=1))
    ids = {row["item_id"] for row in results}

    assert ids == {"id-new"}


def test_item_with_no_sentiment_score_still_returned_with_null_fields(db_path):
    save_news_item(db_path, _item("id-1", ["AAPL"], "Unscored filing alert", NOW - timedelta(hours=1)))

    results = get_news_items_for_symbol(db_path, "AAPL", since_utc=NOW - timedelta(days=1))

    assert len(results) == 1
    row = results[0]
    assert row["item_id"] == "id-1"
    assert row["sentiment"] is None
    assert row["relevance"] is None
    assert row["source_agent"] is None
