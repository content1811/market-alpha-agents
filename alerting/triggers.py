"""Alert trigger detection + dedup, per section_data_pipeline.md section 4.1.

Implemented here: composite-signal-crosses-threshold, squeeze-risk flag,
stop/target proximity, RVOL+price-spike, filing-match (given already-fetched
EDGAR/TDnet results), upcoming-token-unlock, and sentiment-extreme.
upcoming-token-unlock and sentiment-extreme are now fed by
data/connectors/defillama_unlocks.py (a paid DefiLlama Pro-API connector --
see that module's docstring for the live 2026-08-31 verification that this
turned out not to be free/keyless as originally assumed) and
data/connectors/alternative_me.py (free, keyless Fear&Greed Index),
respectively; per every other trigger function in this file, both take
pre-computed numeric inputs rather than reaching into those connectors
themselves. NOT implemented yet (scoped out, not silently skipped):
earnings-date-approaching and data-pipeline-failure are Phase 6/7
operational concerns (a live scheduled run has an earnings calendar and
pipeline health to check against -- this module's job is the trigger/dedup
mechanics, not sourcing that live state).
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


def upcoming_unlock(pct_of_supply: float, multiple_of_adv: float) -> TriggeredAlert | None:
    """Per docs/plan/section_agents.md section 6 indicator #6 ("Unlock
    schedule"): forward 30-day unlock size as % of circulating supply and
    multiple of 30-day ADV. Thresholds exactly as documented there --
    `<1% supply & <5x ADV` = negligible (no alert); `2-5% or >20x ADV` =
    medium; `>5% single cliff` = high. `>5%` and `>20x` are strictly
    greater-than per that doc's own wording, so pct_of_supply==5.0 or
    multiple_of_adv==20.0 land in the medium bucket, not high/negligible.
    Note the doc leaves a gap between the negligible and medium bands (e.g.
    pct_of_supply=1.0 with multiple_of_adv=5.0 satisfies neither "<1% & <5x"
    nor "2-5% or >20x") -- this function does not invent a threshold for
    that gap and returns None (no alert) for it, same as the negligible
    case, rather than guessing a boundary the plan doesn't specify."""
    if pct_of_supply > 5:
        return TriggeredAlert("upcoming_unlock", "", "high", f"unlock={pct_of_supply:.1f}% of supply (single cliff)")
    if 2 <= pct_of_supply <= 5 or multiple_of_adv > 20:
        return TriggeredAlert(
            "upcoming_unlock", "", "medium", f"unlock={pct_of_supply:.1f}% of supply, {multiple_of_adv:.1f}x ADV"
        )
    return None


def sentiment_extreme(fng_value: int, low_threshold: int = 20, high_threshold: int = 80) -> TriggeredAlert | None:
    """Fires on either extreme of the Alternative.me Fear & Greed Index
    (data/connectors/alternative_me.py), medium severity either way -- an
    extreme reading is a contrarian flag to review open exposure, not a
    directional call in itself, so it doesn't warrant "high" on its own."""
    if fng_value <= low_threshold:
        return TriggeredAlert("sentiment_extreme", "", "medium", f"Fear&Greed={fng_value} (extreme fear)")
    if fng_value >= high_threshold:
        return TriggeredAlert("sentiment_extreme", "", "medium", f"Fear&Greed={fng_value} (extreme greed)")
    return None


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
