"""SEC EDGAR real-time filings poller, per
docs/plan/section_agents.md section 8 and section_orchestration.md Phase 5.
Free, keyless, real-time -- the primary structured US filing-trigger source.
Requires a descriptive User-Agent per SEC's fair-access policy (10 req/sec cap).
"""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import feedparser

EDGAR_GETCURRENT_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=include&count=100&output=atom"
SEC_RATE_LIMIT_PER_SEC = 10

# "auto-escalated to High if filing type is 'material event'/8-K Item 2.02,
# 5.02, etc." -- section_data_pipeline.md section 4.1. This set is the
# commonly-cited material-event item numbers; not exhaustive of every possible
# 8-K item, but covers the plan's own named examples plus the standard set.
MATERIAL_EVENT_ITEMS = {
    "1.01", "1.03", "2.01", "2.02", "2.04", "2.05", "2.06", "3.01", "4.01", "4.02", "5.01", "5.02",
}

ITEM_PATTERN = re.compile(r"Item\s+(\d+\.\d+)")


@dataclass
class EdgarFiling:
    accession_number: str
    company_name: str
    cik: str
    form_type: str
    items: list[str]
    filed_at: datetime
    url: str
    is_material_event: bool


def _parse_entry(entry) -> EdgarFiling | None:
    title_match = re.match(r"(\S+) - (.+?) \((\d+)\) \(Filer\)", entry.title)
    if not title_match:
        return None
    form_type, company_name, cik = title_match.groups()

    items = ITEM_PATTERN.findall(entry.summary)
    accession_number = entry.id.split("=")[-1]
    updated = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

    return EdgarFiling(
        accession_number=accession_number,
        company_name=company_name,
        cik=cik,
        form_type=form_type,
        items=items,
        filed_at=updated,
        url=entry.link,
        is_material_event=any(item in MATERIAL_EVENT_ITEMS for item in items),
    )


class EdgarFeedPoller:
    """Polls the getcurrent Atom feed and de-dupes by accession number via a
    local SQLite table, so re-polling the same feed window never re-alerts on
    a filing already seen -- per Phase 5's test requirement ("confirm EDGAR
    poller correctly de-dupes")."""

    def __init__(self, db_path: str = "data/state.db", user_agent: str = "market-alpha-agents research contact@example.com"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("CREATE TABLE IF NOT EXISTS edgar_seen (accession_number TEXT PRIMARY KEY, seen_at REAL)")
        self._conn.commit()
        self._user_agent = user_agent
        self._last_request_time = 0.0

    def _respect_rate_limit(self) -> None:
        min_interval = 1.0 / SEC_RATE_LIMIT_PER_SEC
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    def poll(self) -> list[EdgarFiling]:
        self._respect_rate_limit()
        parsed = feedparser.parse(EDGAR_GETCURRENT_URL, agent=self._user_agent)

        new_filings = []
        for entry in parsed.entries:
            filing = _parse_entry(entry)
            if filing is None:
                continue
            already_seen = self._conn.execute(
                "SELECT 1 FROM edgar_seen WHERE accession_number = ?", (filing.accession_number,)
            ).fetchone()
            if already_seen:
                continue
            self._conn.execute(
                "INSERT INTO edgar_seen (accession_number, seen_at) VALUES (?, ?)",
                (filing.accession_number, time.time()),
            )
            new_filings.append(filing)
        self._conn.commit()
        return new_filings

    def close(self) -> None:
        self._conn.close()


if __name__ == "__main__":
    poller = EdgarFeedPoller(db_path="data/state.db")
    filings = poller.poll()
    print(f"Fetched {len(filings)} new filings")
    for f in filings[:5]:
        print(f"  {f.form_type} {f.company_name} items={f.items} material={f.is_material_event}")
    poller.close()
