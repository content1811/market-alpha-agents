"""CCXT adapter -- keyless public REST access to exchange OHLCV/funding/OI.
See docs/plan/section_data_pipeline.md section 1 ("Explicitly excluded" note
recommends CCXT as the abstraction over hitting exchange REST directly).
"""
from __future__ import annotations

from datetime import datetime, timezone

import ccxt

from data.connectors.base import DataSource
from data.schema import AssetClass, DataQualityFlag, NormalizedBar


class CCXTSource(DataSource):
    name = "ccxt_binance_public"

    def __init__(self, *args, exchange_id: str = "binance", **kwargs):
        super().__init__(*args, **kwargs)
        self._exchange = getattr(ccxt, exchange_id)()

    def get_ohlcv(self, symbol: str, lookback_days: int) -> list[NormalizedBar]:
        # CCXT unified symbol format, e.g. "BTC/USDT"
        ohlcv = self._exchange.fetch_ohlcv(symbol, timeframe="1d", limit=lookback_days)
        if not ohlcv:
            raise ValueError(f"ccxt returned no data for {symbol}")

        now = datetime.now(timezone.utc)
        bars = []
        for ts_ms, open_, high, low, close, volume in ohlcv:
            bars.append(
                NormalizedBar(
                    symbol=symbol,
                    exchange=self._exchange.id,
                    asset_class=AssetClass.CRYPTO,
                    ts_utc=datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
                    open=float(open_),
                    high=float(high),
                    low=float(low),
                    close=float(close),
                    volume=float(volume),
                    adjusted=True,  # no splits/dividends in crypto spot; convention is trivially satisfied
                    adjustment_factor=1.0,
                    source=self.name,
                    ingested_at=now,
                    data_quality_flag=DataQualityFlag.OK,
                )
            )
        return bars


if __name__ == "__main__":
    source = CCXTSource()
    bars = source.get_ohlcv("BTC/USDT", lookback_days=5)
    print(f"Fetched {len(bars)} bars for BTC/USDT on {source._exchange.id}")
    print(bars[-1].model_dump_json(indent=2))
