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

    def get_funding_rate_history(self, symbol: str, since_ms: int, limit_per_call: int = 1000) -> list[dict]:
        """Paginated fetch of a perpetual future's funding-rate history via
        CCXT's unified fetch_funding_rate_history -- keyless, verified live
        against Binance's public endpoint (goes back to that market's 2019
        launch; a single call caps out well short of that, so this pages
        forward from `since_ms` by re-querying with the last returned
        timestamp+1 until it catches up to "now"). `symbol` must be the
        unified perpetual-swap symbol (e.g. "BTC/USDT:USDT"), not the spot
        symbol get_ohlcv() takes. Funding prints every 8h for USDT-margined
        perpetuals (periods_per_day=3), matching
        signals/crypto_composite.py's compute_crypto_derivatives/
        crypto_derivatives_funding_signal_series default. Returns
        {"timestamp" (ms, UTC), "funding_rate"} dicts, oldest first.
        """
        all_rows: list[dict] = []
        cursor = since_ms
        while True:
            batch = self._exchange.fetch_funding_rate_history(symbol, since=cursor, limit=limit_per_call)
            if not batch:
                break
            all_rows.extend(batch)
            last_ts = batch[-1]["timestamp"]
            if last_ts <= cursor:
                break  # safety: no forward progress, avoid an infinite loop
            cursor = last_ts + 1
            if len(batch) < limit_per_call:
                break  # caught up to the most recent available print
        if not all_rows:
            raise ValueError(f"ccxt returned no funding rate history for {symbol}")
        return [{"timestamp": r["timestamp"], "funding_rate": r["fundingRate"]} for r in all_rows]


if __name__ == "__main__":
    source = CCXTSource()
    bars = source.get_ohlcv("BTC/USDT", lookback_days=5)
    print(f"Fetched {len(bars)} bars for BTC/USDT on {source._exchange.id}")
    print(bars[-1].model_dump_json(indent=2))
