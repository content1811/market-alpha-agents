"""Live test for data/parquet_store.py: fetches real AAPL bars via
YFinanceSource, writes them into a tmp Parquet lake, then writes an
overlapping window a second time to prove write_bars' read-merge-dedup-
rewrite path is safe to call repeatedly (e.g. once per daily scan) rather
than just correct on a first, empty-file write. Requires network access.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from data.connectors.us_equities_yfinance import YFinanceSource
from data.parquet_store import read_bars, write_bars

SYMBOL = "AAPL"


@pytest.mark.network
def test_write_bars_dedup_on_repeated_overlapping_write(tmp_path):
    source = YFinanceSource()
    bars = source.get_ohlcv(SYMBOL, lookback_days=60)
    assert len(bars) >= 30, "expected several weeks of real trading days for AAPL"

    base_dir = str(tmp_path / "parquet")
    write_bars(bars, base_dir=base_dir)

    overlapping = bars[-15:]  # re-write the most recent ~3 trading weeks
    write_bars(overlapping, base_dir=base_dir)

    ts_values = sorted(b.ts_utc for b in bars)
    start = ts_values[0].strftime("%Y-%m-%d")
    end = (ts_values[-1] + timedelta(days=1)).strftime("%Y-%m-%d")

    df = read_bars(base_dir, "us_equity", SYMBOL, start=start, end=end)

    assert len(df) == len(bars), "second overlapping write must not duplicate rows"
    assert df["ts_utc"].duplicated().sum() == 0
    assert df["ts_utc"].min().date() == ts_values[0].date()
    assert df["ts_utc"].max().date() == ts_values[-1].date()
    assert list(df["ts_utc"]) == sorted(df["ts_utc"]), "read_bars must return rows sorted by ts_utc"


@pytest.mark.network
def test_write_bars_partitions_by_asset_class_symbol_year_month(tmp_path):
    source = YFinanceSource()
    bars = source.get_ohlcv(SYMBOL, lookback_days=60)

    base_dir = tmp_path / "parquet"
    write_bars(bars, base_dir=str(base_dir))

    months_present = {(b.ts_utc.year, b.ts_utc.month) for b in bars}
    for year, month in months_present:
        expected_path = base_dir / "us_equity" / SYMBOL / f"{year:04d}" / f"{month:02d}.parquet"
        assert expected_path.exists(), f"expected partition file at {expected_path}"
