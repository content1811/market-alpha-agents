"""TDnet (JP timely-disclosure portal) scraper, per
docs/plan/section_agents.md section 8 and section_orchestration.md Phase 5.
No feed exists for TSE disclosures -- HTML scrape only, flagged as added
engineering cost in the plan. Live page structure verified 2026-08-26:
https://www.release.tdnet.info/inbs/I_list_NNN_YYYYMMDD.html, a paginated
table (100 rows/page) with columns time/code/company/title/xbrl/exchange.

Phase 5's explicit test requirement: "confirm TDnet scraper survives a schema
change gracefully (log-and-skip, don't crash the whole run)" -- every row is
parsed inside its own try/except, and the top-level table lookup itself
degrades to an empty list with a warning rather than raising, since this
portal has no feed/API/versioning to signal a breaking change in advance.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

TDNET_BASE_URL = "https://www.release.tdnet.info/inbs"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


@dataclass
class TDnetDisclosure:
    time_jst: str
    code: str
    ticker: str  # 4-digit TSE ticker + ".T", e.g. "7203.T"
    company_name: str
    title: str
    pdf_url: str | None
    exchange: str


def _list_url(as_of: date, page: int = 1) -> str:
    return f"{TDNET_BASE_URL}/I_list_{page:03d}_{as_of.strftime('%Y%m%d')}.html"


def _parse_row(row) -> TDnetDisclosure | None:
    try:
        cells = row.find_all("td")
        if len(cells) < 6:
            return None
        time_jst = cells[0].get_text(strip=True)
        code = cells[1].get_text(strip=True)
        company_name = cells[2].get_text(strip=True)
        title_link = cells[3].find("a")
        title = title_link.get_text(strip=True) if title_link else cells[3].get_text(strip=True)
        pdf_href = title_link.get("href") if title_link else None
        pdf_url = f"{TDNET_BASE_URL}/{pdf_href}" if pdf_href else None
        exchange = cells[5].get_text(strip=True)

        ticker = f"{code[:4]}.T" if len(code) >= 4 and code[:4].isdigit() else code

        return TDnetDisclosure(
            time_jst=time_jst, code=code, ticker=ticker, company_name=company_name,
            title=title, pdf_url=pdf_url, exchange=exchange,
        )
    except Exception:
        logger.warning("TDnet row parse failed, skipping row", exc_info=True)
        return None


def fetch_disclosures(as_of: date | None = None, page: int = 1, timeout: float = 15.0) -> list[TDnetDisclosure]:
    """Fetches one page (100 rows) of today's (or `as_of`'s) TDnet
    disclosures. Returns [] and logs a warning on any structural failure --
    never raises, per the plan's log-and-skip requirement."""
    as_of = as_of or date.today()
    url = _list_url(as_of, page)

    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException:
        logger.warning("TDnet fetch failed for %s", url, exc_info=True)
        return []

    try:
        soup = BeautifulSoup(response.content, "html.parser")
        table = soup.find("table", id="main-list-table")
        if table is None:
            logger.warning("TDnet page structure changed: 'main-list-table' not found at %s", url)
            return []
        rows = table.find_all("tr")
    except Exception:
        logger.warning("TDnet page parse failed for %s", url, exc_info=True)
        return []

    disclosures = []
    for row in rows:
        parsed = _parse_row(row)
        if parsed is not None:
            disclosures.append(parsed)
    return disclosures


def filter_for_watchlist(disclosures: list[TDnetDisclosure], watchlist_tickers: set[str]) -> list[TDnetDisclosure]:
    return [d for d in disclosures if d.ticker in watchlist_tickers]


if __name__ == "__main__":
    results = fetch_disclosures()
    print(f"Fetched {len(results)} disclosures")
    for d in results[:5]:
        print(f"  {d.time_jst} {d.ticker} {d.company_name}: {d.title}")
