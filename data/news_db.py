"""data/news.db (SQLite): news_items and sentiment_scores, per
docs/plan/section_data_pipeline.md section 2.3's rationale for keeping news
out of the Parquet lake -- this is high-cardinality text with lookups by
symbol/date, not large-scale numeric scans, so SQLite is the right tool here
rather than "just because everything else is Parquet".

sentiment_scores is a separate table (not columns bolted onto news_items)
because the two-pass FinBERT/local-LLM scoring pipeline (section 3.2) can
score the same item more than once, from different source_agents, at
different times -- an item can also have zero scores yet (e.g. filing
alerts, section 3.2 step 7, bypass scoring entirely), which the LEFT JOIN in
get_news_items_for_symbol preserves rather than excluding.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from data.schema import NormalizedNewsItem


def init_news_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS news_items (
            item_id TEXT PRIMARY KEY,
            symbol_tags_json TEXT NOT NULL,
            headline TEXT NOT NULL,
            summary TEXT,
            source TEXT NOT NULL,
            url TEXT NOT NULL,
            published_at_utc TEXT NOT NULL,
            ingested_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sentiment_scores (
            item_id TEXT NOT NULL,
            source_agent TEXT NOT NULL,
            sentiment REAL NOT NULL,
            relevance REAL NOT NULL,
            scored_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


def save_news_item(db_path: str, item: NormalizedNewsItem) -> None:
    init_news_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO news_items
           (item_id, symbol_tags_json, headline, summary, source, url, published_at_utc, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (item_id) DO UPDATE SET
             symbol_tags_json=excluded.symbol_tags_json, headline=excluded.headline,
             summary=excluded.summary, source=excluded.source, url=excluded.url,
             published_at_utc=excluded.published_at_utc, ingested_at=excluded.ingested_at""",
        (
            item.item_id,
            json.dumps(item.symbol_tags),
            item.headline,
            item.summary,
            item.source,
            item.url,
            item.published_at_utc.isoformat(),
            item.ingested_at.isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def save_sentiment_score(db_path: str, item_id: str, source_agent: str, sentiment: float, relevance: float) -> None:
    init_news_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO sentiment_scores (item_id, source_agent, sentiment, relevance, scored_at) VALUES (?, ?, ?, ?, ?)",
        (item_id, source_agent, sentiment, relevance, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def get_news_items_for_symbol(db_path: str, symbol: str, since_utc: datetime) -> list[dict]:
    init_news_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT n.*, s.source_agent, s.sentiment, s.relevance, s.scored_at
           FROM news_items n
           LEFT JOIN sentiment_scores s ON s.item_id = n.item_id
           WHERE n.symbol_tags_json LIKE ? AND n.published_at_utc >= ?
           ORDER BY n.published_at_utc DESC""",
        (f'%"{symbol}"%', since_utc.isoformat()),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
