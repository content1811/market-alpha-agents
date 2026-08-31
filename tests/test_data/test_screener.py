"""Live test for data/screener.py: writes real bars for a few US tickers
into a tmp Parquet lake, then checks rank_by_return's DuckDB-computed
ranking against an expectation hand-computed from the same fetched bars'
first/last close -- not a hardcoded number, since real market data changes
daily. Requires network access.

Bars are fetched with a buffer beyond LOOKBACK_DAYS (yfinance's `period=`
string is calendar days but doesn't line up exactly with DuckDB's
`now() - INTERVAL`), then both the expectation and rank_by_return itself
apply the same trailing-LOOKBACK_DAYS-from-now filter, so the test isn't
sensitive to that vendor-side slop.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from data.connectors.us_equities_yfinance import YFinanceSource
from data.parquet_store import write_bars
from data.screener import rank_by_return

SYMBOLS = ["AAPL", "MSFT", "GOOGL"]
LOOKBACK_DAYS = 60
FETCH_BUFFER_DAYS = 30


@pytest.mark.network
def test_rank_by_return_matches_hand_computed_ranking(tmp_path):
    source = YFinanceSource()
    base_dir = str(tmp_path / "parquet")
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)

    expected_return_pct = {}
    for symbol in SYMBOLS:
        bars = source.get_ohlcv(symbol, lookback_days=LOOKBACK_DAYS + FETCH_BUFFER_DAYS)
        assert len(bars) >= 20, f"expected several weeks of real trading days for {symbol}"
        write_bars(bars, base_dir=base_dir)

        windowed = sorted((b for b in bars if b.ts_utc >= cutoff), key=lambda b: b.ts_utc)
        assert len(windowed) >= 2, f"expected multiple bars within the trailing {LOOKBACK_DAYS}d window for {symbol}"
        earliest_close, latest_close = windowed[0].close, windowed[-1].close
        expected_return_pct[symbol] = (latest_close - earliest_close) / earliest_close * 100

    expected_order = sorted(expected_return_pct, key=lambda s: expected_return_pct[s], reverse=True)

    result = rank_by_return(base_dir, "us_equity", SYMBOLS, lookback_days=LOOKBACK_DAYS)

    assert list(result["symbol"]) == expected_order
    for _, row in result.iterrows():
        assert row["return_pct"] == pytest.approx(expected_return_pct[row["symbol"]], abs=0.05)
