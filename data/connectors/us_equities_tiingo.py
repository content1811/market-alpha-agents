"""Tiingo adapter -- fallback/cross-check source for US equity EOD OHLCV,
per docs/plan/section_data_pipeline.md section 1 (Tiingo row) and section 2.2
(canonical fully-adjusted-close convention). Requires a free API key.

Tiingo's `/tiingo/daily/{ticker}/prices` response carries both the raw OHLCV
and Tiingo's own adjusted (adj*) fields side by side, so unlike yfinance/ccxt
(which only expose the already-adjusted series), `adjustment_factor` here is
computed live from adjClose/close rather than hardcoded to 1.0 -- this is the
real cumulative split/dividend multiplier the schema's audit-reconstruction
field is meant to hold.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests
from pydantic_settings import BaseSettings, SettingsConfigDict

from data.connectors.base import DataSource
from data.schema import AssetClass, DataQualityFlag, NormalizedBar

TIINGO_PRICES_URL = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"


class TiingoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    tiingo_api_key: str | None = None


class TiingoSource(DataSource):
    name = "tiingo"

    def __init__(self, *args, settings: TiingoSettings | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._settings = settings or TiingoSettings()

    def get_ohlcv(self, symbol: str, lookback_days: int) -> list[NormalizedBar]:
        start_date = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).date()
        resp = requests.get(
            TIINGO_PRICES_URL.format(ticker=symbol),
            params={"startDate": start_date.isoformat(), "format": "json"},
            headers={"Authorization": f"Token {self._settings.tiingo_api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            raise ValueError(f"tiingo returned no data for {symbol}")

        now = datetime.now(timezone.utc)
        return [
            NormalizedBar(
                symbol=symbol,
                exchange=None,
                asset_class=AssetClass.US_EQUITY,
                ts_utc=datetime.fromisoformat(row["date"]),
                open=float(row["adjOpen"]),
                high=float(row["adjHigh"]),
                low=float(row["adjLow"]),
                close=float(row["adjClose"]),
                volume=float(row["adjVolume"]),
                adjusted=True,
                adjustment_factor=row["adjClose"] / row["close"],
                source=self.name,
                ingested_at=now,
                data_quality_flag=DataQualityFlag.OK,
            )
            for row in rows
        ]


if __name__ == "__main__":
    source = TiingoSource()
    bars = source.get_ohlcv("AAPL", lookback_days=5)
    print(f"Fetched {len(bars)} bars for AAPL")
    print(bars[-1].model_dump_json(indent=2))
