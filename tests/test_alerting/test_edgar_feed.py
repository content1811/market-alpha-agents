"""Tests for alerting/news_watch/edgar_feed.py. De-dup logic is tested with a
monkeypatched feedparser.parse (no network); a real live poll was already run
manually and confirmed correct parsing + de-dup against the real EDGAR feed.
"""
from __future__ import annotations

import tempfile
import time
import types

import pytest

from alerting.news_watch import edgar_feed
from alerting.news_watch.edgar_feed import EdgarFeedPoller, _parse_entry


def _fake_entry(accession: str, form_type: str, company: str, cik: str, items_html: str):
    return types.SimpleNamespace(
        title=f"{form_type} - {company} ({cik}) (Filer)",
        summary=items_html,
        id=f"urn:tag:sec.gov,2008:accession-number={accession}",
        updated_parsed=time.gmtime(),
        link=f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}-index.htm",
    )


def test_parse_entry_extracts_fields_and_material_flag():
    entry = _fake_entry("0001-26-000001", "8-K", "ACME CORP", "123456", "Item 5.02: Departure of Officer")
    filing = _parse_entry(entry)
    assert filing.company_name == "ACME CORP"
    assert filing.cik == "123456"
    assert filing.items == ["5.02"]
    assert filing.is_material_event is True


def test_parse_entry_non_material_item():
    entry = _fake_entry("0001-26-000002", "8-K", "ACME CORP", "123456", "Item 9.01: Financial Statements and Exhibits")
    filing = _parse_entry(entry)
    assert filing.is_material_event is False


def test_parse_entry_returns_none_on_unexpected_title_format():
    entry = types.SimpleNamespace(title="malformed title", summary="", id="x", updated_parsed=time.gmtime(), link="")
    assert _parse_entry(entry) is None


def test_poller_dedupes_across_calls(monkeypatch):
    entries = [_fake_entry("0001-26-100001", "8-K", "ACME CORP", "123456", "Item 5.02: x")]
    fake_parsed = types.SimpleNamespace(entries=entries)
    monkeypatch.setattr(edgar_feed.feedparser, "parse", lambda *a, **k: fake_parsed)

    with tempfile.TemporaryDirectory() as tmp:
        poller = EdgarFeedPoller(db_path=f"{tmp}/state.db")
        first = poller.poll()
        second = poller.poll()
        assert len(first) == 1
        assert len(second) == 0  # same accession number already seen
        poller.close()


def test_poller_respects_rate_limit(monkeypatch):
    fake_parsed = types.SimpleNamespace(entries=[])
    monkeypatch.setattr(edgar_feed.feedparser, "parse", lambda *a, **k: fake_parsed)

    with tempfile.TemporaryDirectory() as tmp:
        poller = EdgarFeedPoller(db_path=f"{tmp}/state.db")
        start = time.time()
        poller.poll()
        poller.poll()
        elapsed = time.time() - start
        assert elapsed >= 1.0 / edgar_feed.SEC_RATE_LIMIT_PER_SEC
        poller.close()
