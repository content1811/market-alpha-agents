"""Adapter-level regression test mandated by docs/plan/section_data_pipeline.md
section 2.2: pull a known historical split date for a liquid symbol and assert
price continuity across the split boundary once normalized. Requires network
access (hits the live yfinance/Yahoo endpoint).

Note on scope: this only verifies that YFinanceSource's own auto_adjust=True
setting produces a continuous, non-discontinuous series across a real split.
It does NOT verify cross-vendor agreement (e.g. vs. Twelve Data/Tiingo) --
that requires a second live adapter with a real API key and is deferred until
one is implemented, per the fallback sources in section_data_pipeline.md.
"""
from __future__ import annotations

import pytest

from data.connectors.us_equities_yfinance import YFinanceSource

# NVDA executed a 10-for-1 split on 2024-06-10. An adapter that failed to
# normalize consistently across this date would show an ~10x (or ~0.1x) jump.
KNOWN_SPLIT_SYMBOL = "NVDA"
KNOWN_SPLIT_START = "2024-06-03"
KNOWN_SPLIT_END = "2024-06-17"
MAX_SANE_DAILY_MOVE = 0.30  # 30% -- generous for a single mega-cap trading day


@pytest.mark.network
def test_price_continuity_across_known_split_date():
    source = YFinanceSource()
    bars = source.get_ohlcv_range(KNOWN_SPLIT_SYMBOL, KNOWN_SPLIT_START, KNOWN_SPLIT_END)
    assert len(bars) >= 5, "expected several trading days around the split date"

    closes = [b.close for b in bars]
    for prev_close, close in zip(closes, closes[1:]):
        day_over_day_move = abs(close - prev_close) / prev_close
        assert day_over_day_move < MAX_SANE_DAILY_MOVE, (
            f"day-over-day move of {day_over_day_move:.1%} across the split window "
            f"looks like an un-normalized split discontinuity, not real volatility"
        )
