"""Cross-symbol screener queries over the Parquet lake, run directly with
DuckDB rather than read_bars-per-symbol-in-a-loop -- the whole point of
DuckDB here is one SQL query scanning many symbols' files at once. See
docs/plan/section_data_pipeline.md section 2.3's named example ("rank all US
watchlist tickers by 252-day return").
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


def rank_by_return(base_dir: str, asset_class: str, symbols: list[str], lookback_days: int) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame(columns=["symbol", "return_pct"])

    glob_path = str(Path(base_dir) / asset_class / "*" / "*" / "*.parquet")
    con = duckdb.connect()
    try:
        return con.execute(
            """
            WITH windowed AS (
                SELECT symbol, ts_utc, close
                FROM read_parquet(?)
                WHERE symbol IN (SELECT UNNEST(?))
                  AND ts_utc >= now() - to_days(?::INTEGER)
            ),
            bounds AS (
                SELECT
                    symbol,
                    arg_min(close, ts_utc) AS earliest_close,
                    arg_max(close, ts_utc) AS latest_close
                FROM windowed
                GROUP BY symbol
            )
            SELECT
                symbol,
                (latest_close - earliest_close) / earliest_close * 100 AS return_pct
            FROM bounds
            ORDER BY return_pct DESC
            """,
            [glob_path, symbols, lookback_days],
        ).df()
    finally:
        con.close()
