"""Analytical OHLCV store: Parquet files partitioned by asset_class/symbol/
year/month, queried in place with DuckDB rather than ETL'd into another
database. See docs/plan/section_data_pipeline.md section 2.3.

write_bars is designed to be called repeatedly (e.g. once per daily scan, or
once per intraday poll) against the same month's file without duplicating
rows: each affected month is read back, merged with the incoming bars, and
deduplicated by (symbol, ts_utc) keeping the newest row (by ingested_at)
before being rewritten whole. Parquet has no native upsert, so "read, merge,
rewrite the whole file" is the only correct way to keep a monthly partition
append-safe -- there is no smaller unit of update available. The merge/write
itself goes through DuckDB's own Parquet reader/writer (COPY ... TO ...
(FORMAT PARQUET)) rather than pandas.to_parquet/read_parquet, since the
latter requires pyarrow or fastparquet as an extra dependency that isn't
otherwise needed anywhere in this project -- duckdb is already the one
Parquet-capable dependency pyproject.toml declares.
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd

from data.schema import NormalizedBar


def _partition_path(base_dir: str, asset_class: str, symbol: str, year: int, month: int) -> Path:
    return Path(base_dir) / asset_class / symbol / f"{year:04d}" / f"{month:02d}.parquet"


def _sql_literal(path: Path) -> str:
    return str(path).replace("'", "''")


def write_bars(bars: list[NormalizedBar], base_dir: str = "data/parquet") -> None:
    if not bars:
        return

    df = pd.DataFrame([b.model_dump() for b in bars])
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    df["ingested_at"] = pd.to_datetime(df["ingested_at"], utc=True)
    df["asset_class"] = df["asset_class"].apply(lambda v: v.value if hasattr(v, "value") else v)
    df["data_quality_flag"] = df["data_quality_flag"].apply(lambda v: v.value if hasattr(v, "value") else v)
    df["_year"] = df["ts_utc"].dt.year
    df["_month"] = df["ts_utc"].dt.month

    for (asset_class, symbol, year, month), group in df.groupby(["asset_class", "symbol", "_year", "_month"]):
        group = group.drop(columns=["_year", "_month"]).reset_index(drop=True)
        path = _partition_path(base_dir, asset_class, symbol, year, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".parquet.tmp")

        con = duckdb.connect()
        con.register("new_bars", group)
        if path.exists():
            con.execute(
                f"""
                COPY (
                    SELECT * EXCLUDE (_rn) FROM (
                        SELECT *, ROW_NUMBER() OVER (
                            PARTITION BY symbol, ts_utc ORDER BY ingested_at DESC
                        ) AS _rn
                        FROM (
                            SELECT * FROM read_parquet('{_sql_literal(path)}')
                            UNION ALL BY NAME
                            SELECT * FROM new_bars
                        )
                    )
                    WHERE _rn = 1
                    ORDER BY ts_utc
                ) TO '{_sql_literal(tmp_path)}' (FORMAT PARQUET)
                """
            )
        else:
            con.execute(
                f"COPY (SELECT * FROM new_bars ORDER BY ts_utc) TO '{_sql_literal(tmp_path)}' (FORMAT PARQUET)"
            )
        con.close()
        os.replace(tmp_path, path)


def read_bars(base_dir: str, asset_class: str, symbol: str, start: str, end: str) -> pd.DataFrame:
    glob_path = str(Path(base_dir) / asset_class / symbol / "*" / "*.parquet")
    con = duckdb.connect()
    try:
        return con.execute(
            "SELECT * FROM read_parquet(?) WHERE ts_utc >= ? AND ts_utc < ? ORDER BY ts_utc",
            [glob_path, start, end],
        ).df()
    finally:
        con.close()


if __name__ == "__main__":
    from datetime import datetime, timezone

    from data.connectors.us_equities_yfinance import YFinanceSource

    source = YFinanceSource()
    bars = source.get_ohlcv("AAPL", lookback_days=10)
    write_bars(bars, base_dir="data/parquet")
    print(f"Wrote {len(bars)} bars for AAPL")

    df = read_bars(
        "data/parquet",
        "us_equity",
        "AAPL",
        start="2000-01-01",
        end=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    print(f"Read back {len(df)} rows")
    print(df.tail())
