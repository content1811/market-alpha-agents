"""Tests for alerting/news_watch/tdnet_scraper.py. A real live scrape was
already run manually against today's actual TDnet page and confirmed correct
(5202.T Nippon Sheet Glass, etc.) -- these tests cover graceful degradation
on a schema change, which is the Phase 5 test requirement, using
BeautifulSoup on fixture HTML (no network).
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from alerting.news_watch import tdnet_scraper
from alerting.news_watch.tdnet_scraper import _parse_row, fetch_disclosures, filter_for_watchlist

GOOD_ROW_HTML = """
<tr>
<td class="oddnew-L kjTime" noWrap>22:00</td>
<td class="oddnew-M kjCode" noWrap>52020</td>
<td class="oddnew-M kjName" noWrap>板硝子</td>
<td class="oddnew-M kjTitle" align="left"><a href="140120260825525828.pdf" target="_blank">財務上の特約について</a></td>
<td class="oddnew-M kjXbrl" noWrap align="center"> </td>
<td class="oddnew-M kjPlace" noWrap align="left">東</td>
<td class="oddnew-R kjHistroy" align="left">　</td>
</tr>
"""

MALFORMED_ROW_HTML = "<tr><td>only one cell</td></tr>"


def _row_from_html(html: str):
    return BeautifulSoup(html, "html.parser").find("tr")


def test_parse_row_extracts_fields_and_ticker():
    disclosure = _parse_row(_row_from_html(GOOD_ROW_HTML))
    assert disclosure.code == "52020"
    assert disclosure.ticker == "5202.T"
    assert disclosure.company_name == "板硝子"
    assert disclosure.title == "財務上の特約について"
    assert disclosure.pdf_url == "https://www.release.tdnet.info/inbs/140120260825525828.pdf"


def test_parse_row_returns_none_on_too_few_cells():
    assert _parse_row(_row_from_html(MALFORMED_ROW_HTML)) is None


def test_fetch_disclosures_degrades_gracefully_on_missing_table(monkeypatch):
    class FakeResponse:
        content = b"<html><body>completely different page structure now</body></html>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(tdnet_scraper.requests, "get", lambda *a, **k: FakeResponse())

    result = fetch_disclosures()
    assert result == []  # log-and-skip, never raises


def test_fetch_disclosures_degrades_gracefully_on_network_failure(monkeypatch):
    import requests as real_requests

    def raise_error(*args, **kwargs):
        raise real_requests.ConnectionError("simulated network failure")

    monkeypatch.setattr(tdnet_scraper.requests, "get", raise_error)

    result = fetch_disclosures()
    assert result == []


def test_filter_for_watchlist():
    from alerting.news_watch.tdnet_scraper import TDnetDisclosure

    disclosures = [
        TDnetDisclosure("22:00", "52020", "5202.T", "A", "title a", None, "東"),
        TDnetDisclosure("21:00", "72030", "7203.T", "B", "title b", None, "東"),
    ]
    filtered = filter_for_watchlist(disclosures, {"7203.T"})
    assert len(filtered) == 1
    assert filtered[0].ticker == "7203.T"
