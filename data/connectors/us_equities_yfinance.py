"""yfinance adapter -- primary live source for US equities. Keyless, but
undocumented/unofficial: needs a browser User-Agent and tolerates throttling.
See docs/plan/section_data_pipeline.md section 1.
"""
from __future__ import annotations

from datetime import datetime, timezone

import yfinance as yf

from data.connectors.base import DataSource
from data.schema import AssetClass, DataQualityFlag, NormalizedBar


class YFinanceSource(DataSource):
    name = "yfinance"

    def _bars_from_dataframe(self, symbol: str, df) -> list[NormalizedBar]:
        now = datetime.now(timezone.utc)
        return [
            NormalizedBar(
                symbol=symbol,
                exchange=None,
                asset_class=AssetClass.US_EQUITY,
                ts_utc=ts.to_pydatetime().astimezone(timezone.utc),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]),
                adjusted=True,
                adjustment_factor=1.0,  # yfinance applies the adjustment internally, doesn't expose the raw multiple
                source=self.name,
                ingested_at=now,
                data_quality_flag=DataQualityFlag.OK,
            )
            for ts, row in df.iterrows()
        ]

    def get_ohlcv(self, symbol: str, lookback_days: int) -> list[NormalizedBar]:
        df = yf.Ticker(symbol).history(period=f"{lookback_days}d", auto_adjust=True)
        if df.empty:
            raise ValueError(f"yfinance returned no data for {symbol}")
        # The most recent bar can come back with a NaN close while today's
        # session is still in progress/settling (observed live) -- an
        # unusable row, not a usable one with a missing field, so it's
        # dropped rather than passed through for a downstream z-score/BB
        # calculation to silently turn into NaN.
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        if df.empty:
            raise ValueError(f"yfinance returned only NaN bars for {symbol}")
        return self._bars_from_dataframe(symbol, df)

    def get_ohlcv_range(self, symbol: str, start: str, end: str) -> list[NormalizedBar]:
        """Explicit date-range fetch, used by backtesting (Phase 4) and by the
        split-continuity regression test below -- yfinance's `period=` strings
        only accept a fixed set of values (1d/5d/1mo/.../max), not arbitrary
        day counts, so a historical range needs start/end instead."""
        df = yf.Ticker(symbol).history(start=start, end=end, auto_adjust=True)
        if df.empty:
            raise ValueError(f"yfinance returned no data for {symbol} in [{start}, {end})")
        return self._bars_from_dataframe(symbol, df)


if __name__ == "__main__":
    source = YFinanceSource()
    bars = source.get_ohlcv("AAPL", lookback_days=5)
    print(f"Fetched {len(bars)} bars for AAPL")
    print(bars[-1].model_dump_json(indent=2))
