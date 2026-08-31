"""Twelve Data adapter -- fallback/cross-check source for US equity EOD OHLCV,
per docs/plan/section_data_pipeline.md section 1 (Twelve Data row) and section
2.2 (canonical fully-adjusted-close convention). Requires a free API key.

`time_series` returns newest-first and does not expose a raw/adjusted split,
so ordering is flipped here and, per a live split-continuity check against
NVDA's 2024-06-10 10-for-1 split (no ~10x discontinuity across the split
date), the series is confirmed already split-adjusted -- adjustment_factor is
therefore hardcoded to 1.0 like yfinance/ccxt, since Twelve Data doesn't
expose the raw multiple either.
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests
from pydantic_settings import BaseSettings, SettingsConfigDict

from data.connectors.base import DataSource
from data.schema import AssetClass, DataQualityFlag, NormalizedBar

TWELVEDATA_TIME_SERIES_URL = "https://api.twelvedata.com/time_series"


class TwelveDataSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    twelvedata_api_key: str | None = None


class TwelveDataSource(DataSource):
    name = "twelvedata"

    def __init__(self, *args, settings: TwelveDataSettings | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._settings = settings or TwelveDataSettings()

    def get_ohlcv(self, symbol: str, lookback_days: int) -> list[NormalizedBar]:
        resp = requests.get(
            TWELVEDATA_TIME_SERIES_URL,
            params={
                "symbol": symbol,
                "interval": "1day",
                "outputsize": lookback_days,
                "apikey": self._settings.twelvedata_api_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") != "ok":
            raise ValueError(f"twelvedata error for {symbol}: {payload}")
        rows = payload["values"]
        if not rows:
            raise ValueError(f"twelvedata returned no data for {symbol}")

        now = datetime.now(timezone.utc)
        return [
            NormalizedBar(
                symbol=symbol,
                exchange=None,
                asset_class=AssetClass.US_EQUITY,
                ts_utc=datetime.fromisoformat(row["datetime"]).replace(tzinfo=timezone.utc),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                adjusted=True,
                adjustment_factor=1.0,
                source=self.name,
                ingested_at=now,
                data_quality_flag=DataQualityFlag.OK,
            )
            for row in reversed(rows)  # API returns newest-first
        ]


if __name__ == "__main__":
    source = TwelveDataSource()
    bars = source.get_ohlcv("AAPL", lookback_days=5)
    print(f"Fetched {len(bars)} bars for AAPL")
    print(bars[-1].model_dump_json(indent=2))
