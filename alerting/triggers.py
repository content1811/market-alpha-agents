"""Alert trigger detection + dedup, per section_data_pipeline.md section 4.1.

Implemented here: composite-signal-crosses-threshold, squeeze-risk flag,
stop/target proximity, RVOL+price-spike, and filing-match (given
already-fetched EDGAR/TDnet results). NOT implemented yet (scoped out, not
silently skipped): upcoming-token-unlock and sentiment-extreme+open-exposure
both need data this system doesn't fetch yet (unlock calendars need
CryptoOnChainAgent's still-deferred connector; Fear&Greed needs a new,
currently-unwired Alternative.me integration); earnings-date-approaching and
data-pipeline-failure are Phase 6/7 operational concerns (a live scheduled
run has an earnings calendar and pipeline health to check against -- this
module's job is the trigger/dedup mechanics, not sourcing that live state).
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Severity = Literal["low", "medium", "high"]


@dataclass
class TriggeredAlert:
    trigger_type: str
    symbol: str
    severity: Severity
    detail: str


def composite_score_threshold(blended_score: float, threshold: float = 0.7) -> TriggeredAlert | None:
    if abs(blended_score) >= threshold:
        return TriggeredAlert("composite_score_threshold", "", "high", f"blended_score={blended_score:.2f}")
    return None


def squeeze_risk_flag(squeeze_score: float, threshold: float = 0.6) -> TriggeredAlert | None:
    if squeeze_score >= threshold:
        return TriggeredAlert("squeeze_risk_flag", "", "high", f"squeeze_score={squeeze_score:.2f}")
    return None


def stop_target_proximity(price: float, stop_price: float | None, target_price: float | None, atr14: float) -> TriggeredAlert | None:
    if stop_price is not None and abs(price - stop_price) <= 0.5 * atr14:
        return TriggeredAlert("stop_proximity", "", "high", f"price={price:.2f} near stop={stop_price:.2f}")
    if target_price is not None and abs(price - target_price) <= 0.5 * atr14:
        return TriggeredAlert("target_proximity", "", "medium", f"price={price:.2f} near target={target_price:.2f}")
    return None


def rvol_price_spike(rvol: float, same_bar_return_pct: float, is_crypto: bool = False) -> TriggeredAlert | None:
    rvol_threshold = 4.0 if is_crypto else 3.0
    return_threshold = 4.0 if is_crypto else 2.0
    if rvol >= rvol_threshold and abs(same_bar_return_pct) >= return_threshold:
        return TriggeredAlert("rvol_price_spike", "", "medium", f"RVOL={rvol:.1f}x, return={same_bar_return_pct:+.1f}%")
    return None


def filing_match(form_type: str, is_material_event: bool) -> TriggeredAlert:
    severity: Severity = "high" if is_material_event else "medium"
    return TriggeredAlert("filing_match", "", severity, f"{form_type} filed, material={is_material_event}")


class AlertDeduplicator:
    """(symbol, trigger_type, bucket) key with a cooldown window, per
    section_data_pipeline.md section 4.1, so a symbol hovering exactly at a
    threshold doesn't spam the channel every scheduled cycle."""

    def __init__(self, db_path: str = "data/state.db", cooldown_hours: float = 2.0):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS alert_dedup (symbol TEXT, trigger_type TEXT, sent_at REAL, "
            "PRIMARY KEY (symbol, trigger_type))"
        )
        self._conn.commit()
        self._cooldown_seconds = cooldown_hours * 3600

    def should_send(self, symbol: str, trigger_type: str) -> bool:
        row = self._conn.execute(
            "SELECT sent_at FROM alert_dedup WHERE symbol = ? AND trigger_type = ?", (symbol, trigger_type)
        ).fetchone()
        if row is None:
            return True
        return time.time() - row[0] >= self._cooldown_seconds

    def record_sent(self, symbol: str, trigger_type: str) -> None:
        self._conn.execute(
            "INSERT INTO alert_dedup (symbol, trigger_type, sent_at) VALUES (?, ?, ?) "
            "ON CONFLICT (symbol, trigger_type) DO UPDATE SET sent_at = excluded.sent_at",
            (symbol, trigger_type, time.time()),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
