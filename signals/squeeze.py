"""Pure-math short-squeeze composite for ShortSqueezeAgent, per
docs/plan/section_agents.md section 4. No LLM calls here.

Scope note: si_score/dtc_score/fee_score/util_score all need FINRA short
interest + a borrow-fee/utilization source, neither of which has a connector
built yet (Phase 1 remaining work per README). options_score is the one
sub-component buildable today with real, free, keyless data (yfinance
option_chain()) -- see agents/short_squeeze_agent.py, which runs this
composite in an explicitly degraded mode until the others land.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

WEIGHTS = {"si_score": 0.30, "dtc_score": 0.20, "fee_score": 0.25, "util_score": 0.15, "options_score": 0.10}


@dataclass
class OptionRow:
    strike: float
    last_price: float
    bid: float
    ask: float
    volume: float
    open_interest: float


def options_score(
    rows: list[OptionRow],
    vol_oi_ratio_min: float = 1.25,
    min_volume: float = 500,
    min_open_interest: float = 100,
) -> float:
    """1 if any call strike shows volume/OI >= threshold with bullish skew
    (trades at/above ask) and minimum liquidity, else 0 -- section_agents.md
    section 4 indicator #5 (Barchart-style unusual-options methodology)."""
    for row in rows:
        if row.open_interest <= 0 or row.ask <= 0:
            continue
        vol_oi_ratio = row.volume / row.open_interest
        bullish_skew = row.last_price >= row.ask
        min_liquidity = row.volume > min_volume and row.open_interest > min_open_interest
        if vol_oi_ratio >= vol_oi_ratio_min and bullish_skew and min_liquidity:
            return 1.0
    return 0.0


def si_score(si_pct_of_float: float, divisor: float = 40) -> float:
    return float(np.clip(si_pct_of_float / divisor, 0.0, 1.0))


def dtc_score(days_to_cover: float, divisor: float = 10) -> float:
    return float(np.clip(days_to_cover / divisor, 0.0, 1.0))


def fee_score(borrow_fee_rate_pct: float, divisor: float = 50) -> float:
    return float(np.clip(borrow_fee_rate_pct / divisor, 0.0, 1.0))


def util_score(utilization_pct: float, offset: float = 80, scale: float = 20) -> float:
    return float(np.clip((utilization_pct - offset) / scale, 0.0, 1.0))


@dataclass
class SqueezeSubScores:
    si_score: float
    dtc_score: float
    fee_score: float
    util_score: float
    options_score: float
    signal_score: float
    confidence: float
    degraded_fields: list[str]


def compute_squeeze(
    si_pct_of_float: float | None,
    days_to_cover: float | None,
    borrow_fee_rate_pct: float | None,
    utilization_pct: float | None,
    option_rows: list[OptionRow] | None,
    rvol: float | None = None,
    is_jp: bool = False,
) -> SqueezeSubScores:
    """signal_score = weighted_avg(si_score:0.3, dtc_score:0.2, fee_score:0.25,
    util_score:0.15, options_score:0.10), one-sided/never negative, per
    section_agents.md section 4. Missing inputs are excluded from the weighted
    average entirely (re-normalized over available weight) rather than
    silently treated as 0 -- a missing SI% is not evidence of "no squeeze
    risk," it's an unknown, so it must not pull the score toward zero."""
    degraded_fields = []
    components = {}

    if si_pct_of_float is not None:
        components["si_score"] = si_score(si_pct_of_float)
    else:
        degraded_fields.append("si_score (FINRA short interest not connected)")

    if days_to_cover is not None:
        components["dtc_score"] = dtc_score(days_to_cover)
    else:
        degraded_fields.append("dtc_score (requires short interest + avg volume)")

    if borrow_fee_rate_pct is not None:
        components["fee_score"] = fee_score(borrow_fee_rate_pct)
    else:
        degraded_fields.append("fee_score (borrow-fee source not connected)")

    if utilization_pct is not None:
        components["util_score"] = util_score(utilization_pct)
    else:
        degraded_fields.append("util_score (utilization source not connected)")

    opt_score = options_score(option_rows) if option_rows else 0.0
    components["options_score"] = opt_score
    if not option_rows:
        degraded_fields.append("options_score (no options chain data provided)")

    total_weight = sum(WEIGHTS[k] for k in components)
    if total_weight == 0:
        signal_score = 0.0
    else:
        signal_score = sum(WEIGHTS[k] * v for k, v in components.items()) / total_weight
    signal_score = float(np.clip(signal_score, 0.0, 1.0))  # never negative, per spec

    if rvol is not None and rvol >= 5:
        signal_score = min(1.0, signal_score * 1.1)  # RVOL cross-check raises confidence, not just score

    # confidence: high only with fresh borrow-fee/utilization data (rare on
    # free tier); degraded to <=0.4 on lagged-FINRA-only; floored near 0.2
    # for JP; here, with SI/DTC/fee/util ALL unavailable, cap even lower.
    if "fee_score" in components and "util_score" in components:
        confidence = 0.7
    elif "si_score" in components:
        confidence = 0.4
    else:
        confidence = 0.15  # only options_score available -- more degraded than the plan's worst-documented case
    if is_jp:
        confidence = min(confidence, 0.2)

    return SqueezeSubScores(
        si_score=components.get("si_score", 0.0),
        dtc_score=components.get("dtc_score", 0.0),
        fee_score=components.get("fee_score", 0.0),
        util_score=components.get("util_score", 0.0),
        options_score=opt_score,
        signal_score=signal_score,
        confidence=confidence,
        degraded_fields=degraded_fields,
    )
