"""JP equities via Yahoo's unofficial chart endpoint (same underlying vendor
endpoint the yfinance library wraps, applied to .T tickers). This is currently
the ONLY live source for JP equities -- see docs/plan/section_data_pipeline.md
section 1, "JP-equity live-data asymmetry": J-Quants Free is 12wk-lagged
reference data only, not a real live fallback. Kept as its own module (rather
than reusing YFinanceSource directly) because its circuit-breaker/fallback
semantics are asset-class-specific: when this source is down, JP equities have
no live fallback at all, per the "JP data unavailable" mode in that section.
"""
from __future__ import annotations

from datetime import datetime, timezone

import yfinance as yf

from data.connectors.base import DataSource
from data.schema import AssetClass, DataQualityFlag, NormalizedBar


class JPEquitiesYahooSource(DataSource):
    name = "yahoo_unofficial"

    def get_ohlcv(self, symbol: str, lookback_days: int) -> list[NormalizedBar]:
        if not symbol.endswith(".T"):
            raise ValueError(f"expected a .T ticker for JP equities, got {symbol!r}")

        ticker = yf.Ticker(symbol)
        df = ticker.history(period=f"{lookback_days}d", auto_adjust=True)
        if df.empty:
            raise ValueError(f"yahoo_unofficial returned no data for {symbol}")

        now = datetime.now(timezone.utc)
        bars = []
        for ts, row in df.iterrows():
            bars.append(
                NormalizedBar(
                    symbol=symbol,
                    exchange="TSE",
                    asset_class=AssetClass.JP_EQUITY,
                    ts_utc=ts.to_pydatetime().astimezone(timezone.utc),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row["Volume"]),
                    adjusted=True,
                    adjustment_factor=1.0,
                    source=self.name,
                    ingested_at=now,
                    data_quality_flag=DataQualityFlag.OK,
                )
            )
        return bars


if __name__ == "__main__":
    source = JPEquitiesYahooSource()
    bars = source.get_ohlcv("7203.T", lookback_days=5)
    print(f"Fetched {len(bars)} bars for 7203.T (Toyota)")
    print(bars[-1].model_dump_json(indent=2))
