"""DataSource ABC shared by every adapter in data/connectors/.

Encodes the rate-limit ledger, read-through cache, and circuit-breaker design
from docs/plan/section_data_pipeline.md sections 2.3-2.4 in one place so
individual adapters (yfinance, ccxt, jquants, ...) only implement the
vendor-specific fetch + normalization logic.
"""
from __future__ import annotations

import sqlite3
import time
from abc import ABC, abstractmethod
from pathlib import Path

import diskcache

from data.schema import DataQualityFlag, NormalizedBar


class CircuitBrokenError(Exception):
    """Raised when a source's circuit breaker is open -- caller should fail
    over to the configured fallback or mark data_quality_flag=unavailable."""


class RateLimiter:
    """Token-bucket ledger backed by SQLite, per section_data_pipeline.md
    section 2.4: before any request, count calls within the trailing window
    and compare against the source's documented cap."""

    def __init__(self, db_path: str, source: str, max_calls: int, window_seconds: float):
        self.source = source
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS rate_limit_calls (source TEXT, ts_utc REAL)"
        )
        self._conn.commit()

    def allow(self) -> bool:
        now = time.time()
        cutoff = now - self.window_seconds
        count = self._conn.execute(
            "SELECT COUNT(*) FROM rate_limit_calls WHERE source = ? AND ts_utc > ?",
            (self.source, cutoff),
        ).fetchone()[0]
        return count < self.max_calls

    def record(self) -> None:
        self._conn.execute(
            "INSERT INTO rate_limit_calls (source, ts_utc) VALUES (?, ?)",
            (self.source, time.time()),
        )
        self._conn.commit()


class CircuitBreaker:
    """Skip a source for the rest of the run after repeated 429/5xx, per
    section_data_pipeline.md section 2.4. Exponential backoff base 2s, capped
    at 5 minutes, with a hard trip after too many consecutive failures."""

    def __init__(self, base_seconds: float = 2.0, cap_seconds: float = 300.0, trip_after: int = 5):
        self.base_seconds = base_seconds
        self.cap_seconds = cap_seconds
        self.trip_after = trip_after
        self._consecutive_failures = 0
        self._tripped_until: float = 0.0

    @property
    def is_open(self) -> bool:
        return time.time() < self._tripped_until

    def record_success(self) -> None:
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.trip_after:
            backoff = min(self.base_seconds * (2 ** self._consecutive_failures), self.cap_seconds)
            self._tripped_until = time.time() + backoff


class DataSource(ABC):
    """One thin adapter per vendor. Vendor-specific quirks (timezone, currency,
    symbol convention, price-adjustment normalization) live only here -- never
    downstream. See section_data_pipeline.md section 2.2."""

    #: Human-readable source name, matches config.yaml data_sources block.
    name: str = "unset"

    def __init__(self, cache_dir: str = "data/cache", rate_limit_db: str = "data/state.db"):
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        Path(rate_limit_db).parent.mkdir(parents=True, exist_ok=True)
        self._cache = diskcache.Cache(cache_dir)
        self._breaker = CircuitBreaker()

    @abstractmethod
    def get_ohlcv(self, symbol: str, lookback_days: int) -> list[NormalizedBar]:
        """Fetch and normalize OHLCV bars for one symbol. Must set
        adjusted=True and the fully-adjusted-close convention before
        returning -- see section_data_pipeline.md section 2.2."""

    def cached_get_ohlcv(
        self, symbol: str, lookback_days: int, ttl_seconds: float
    ) -> tuple[list[NormalizedBar], DataQualityFlag]:
        """Read-through cache wrapper. Returns (bars, flag) where flag follows
        the canonical stale/unavailable propagation rule (section 2.4): OK if
        age <= ttl_seconds, STALE if ttl_seconds < age <= 2x ttl_seconds,
        UNAVAILABLE once no usable cached value exists at all (which is also
        when diskcache itself evicts the entry, since we key its own expiry to
        exactly 2x ttl_seconds below -- diskcache hides a value entirely once
        it passes its own expiry, so relying on diskcache's expire_time to
        detect "past 1x but within 2x TTL" does not work; the ingested_at
        timestamp is therefore stored alongside the value and staleness is
        computed from it explicitly)."""
        key = (self.name, "ohlcv", symbol, lookback_days)

        def read_cache():
            cached = self._cache.get(key, default=None)
            if cached is None:
                return None, None
            bars, ingested_ts = cached
            age = time.time() - ingested_ts
            if age <= ttl_seconds:
                return bars, DataQualityFlag.OK
            return bars, DataQualityFlag.STALE  # diskcache guarantees age <= 2x ttl_seconds here

        if self._breaker.is_open:
            bars, flag = read_cache()
            return (bars or [], flag or DataQualityFlag.UNAVAILABLE)

        try:
            bars = self.get_ohlcv(symbol, lookback_days)
            self._cache.set(key, (bars, time.time()), expire=2 * ttl_seconds)
            self._breaker.record_success()
            return bars, DataQualityFlag.OK
        except Exception:
            self._breaker.record_failure()
            bars, flag = read_cache()
            return (bars or [], flag or DataQualityFlag.UNAVAILABLE)
