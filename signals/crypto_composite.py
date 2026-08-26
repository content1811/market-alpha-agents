"""Pure-math crypto composite signals for CryptoDerivativesAgent (section 7)
and CryptoOnChainAgent (section 6) of docs/plan/section_agents.md.

Scope note on oi_score: the plan's 2x2 price/OI table is described in
"+10/+5/0" point-scale language, not a precise clip() formula like the other
indicators -- mapping it onto [-1,1] is a documented judgment call (see
OI_SCORE_MAP below), not a mechanical translation. (price down, OI up) is
deliberately left at 0.0 directionally per the plan's own "flag, no fixed
sign" framing, surfaced instead via `squeeze_risk_flag`.

Scope note on skew_score: Deribit's public options chain is the source the
plan names, but it flags "prior 404s observed" on the endpoint -- not wired
to a live connector yet. `skew_z=None` (the default) skips this sub-score
rather than guessing, per CryptoDerivativesAgent's own note that skew is
"low-weight/slow-calibrating" on free-tier data.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# (price_direction, oi_direction) -> score, per section_agents.md section 7 indicator #2.
OI_SCORE_MAP = {
    (1, 1): 1.0,  # price up, OI up: trend confirmation ("+10")
    (1, -1): 0.25,  # price up, OI down: weak short-covering rally ("0 to +5")
    (-1, 1): 0.0,  # price down, OI up: fresh-short buildup -- flagged separately, no fixed sign
    (-1, -1): 0.25,  # price down, OI down: deleveraging, mildly contrarian-bullish once stabilized ("+5")
}


@dataclass
class CryptoDerivativesSubScores:
    funding_score: float
    oi_score: float
    skew_score: float
    signal_score: float
    squeeze_risk_flag: bool
    confidence: float


def annualized_funding_rate(funding_rate_per_period: float, periods_per_day: int = 3) -> float:
    return funding_rate_per_period * periods_per_day * 365


def compute_crypto_derivatives(
    funding_rate_history: list[float],
    current_price: float,
    prior_price: float,
    current_oi: float,
    prior_oi: float,
    skew_z: float | None = None,
    periods_per_day: int = 3,
) -> CryptoDerivativesSubScores:
    annualized = [annualized_funding_rate(r, periods_per_day) for r in funding_rate_history]
    mean, std = float(np.mean(annualized)), float(np.std(annualized))
    current_annualized = annualized[-1]
    funding_z = (current_annualized - mean) / std if std else 0.0
    funding_score = float(np.clip(-funding_z / 2, -1.0, 1.0))

    price_dir = 1 if current_price >= prior_price else -1
    oi_dir = 1 if current_oi >= prior_oi else -1
    oi_score = OI_SCORE_MAP[(price_dir, oi_dir)]
    squeeze_risk_flag = price_dir == -1 and oi_dir == 1

    if skew_z is not None:
        skew_score = float(np.clip(-skew_z / 1.5, -1.0, 1.0))
        skew_weight, skew_confidence_available = 0.25, True
    else:
        skew_score, skew_weight, skew_confidence_available = 0.0, 0.0, False

    funding_weight, oi_weight = 0.4, 0.35
    total_weight = funding_weight + oi_weight + skew_weight
    signal_score = float(
        np.clip(
            (funding_weight * funding_score + oi_weight * oi_score + skew_weight * skew_score) / total_weight,
            -1.0,
            1.0,
        )
    )

    # funding/OI are "mechanically grounded" (high confidence per the source
    # research); skew starts low/unavailable on free-tier data.
    confidence = 0.75 if skew_confidence_available else 0.6

    return CryptoDerivativesSubScores(
        funding_score=funding_score,
        oi_score=oi_score,
        skew_score=skew_score,
        signal_score=signal_score,
        squeeze_risk_flag=squeeze_risk_flag,
        confidence=confidence,
    )


@dataclass
class CryptoOnChainSubScores:
    mvrv_score: float
    sopr_score: float
    flow_score: float
    whale_score: float
    addr_divergence_score: float
    unlock_penalty: float
    signal_score: float
    confidence: float


def mvrv_band_score(mvrv: float) -> float:
    """ln(MVRV) percentile-band mapping per section_agents.md section 6
    indicator #1, on the same 0-100 composite scale as the other sub-scores
    below (rescaled to [-1,1] by the composite weighting in compute_onchain)."""
    if mvrv < 1.0:
        return 95.0  # capitulation, bullish-contrarian
    if mvrv < 2.0:
        return 70.0  # accumulation
    if mvrv < 3.5:
        return 50.0  # neutral
    if mvrv < 7.0:
        return 20.0  # overheated
    return 5.0  # extreme historical peak territory


def compute_onchain(
    mvrv: float,
    sopr_score: float,
    flow_score: float,
    whale_score: float,
    addr_divergence_score: float,
    unlock_penalty: float,
) -> CryptoOnChainSubScores:
    """Implements section_agents.md section 6's signal_score computation
    verbatim: onchain_raw = weighted_avg(mvrv_pctile:0.30, sopr:0.20, flow:0.20,
    whale:0.15, addr_divergence:0.05, unlock_penalty:0.10); signal_score =
    clip(onchain_raw/100, -1, 1). All inputs except mvrv are already on the
    0-100-style composite scale the plan uses (callers not yet wired to a
    live on-chain data source -- see docs/research crypto_data.md re: the
    Glassnode-free-tier discontinuation -- should pass sub-scores computed
    from Dune/CryptoQuant once that connector exists)."""
    mvrv_pctile = mvrv_band_score(mvrv)
    onchain_raw = (
        0.30 * mvrv_pctile
        + 0.20 * sopr_score
        + 0.20 * flow_score
        + 0.15 * whale_score
        + 0.05 * addr_divergence_score
        + 0.10 * unlock_penalty
    )
    signal_score = float(np.clip(onchain_raw / 100, -1.0, 1.0))
    confidence = 0.6  # capped per section_agents.md section 6 -- widely-followed/arbitraged signals

    return CryptoOnChainSubScores(
        mvrv_score=mvrv_pctile,
        sopr_score=sopr_score,
        flow_score=flow_score,
        whale_score=whale_score,
        addr_divergence_score=addr_divergence_score,
        unlock_penalty=unlock_penalty,
        signal_score=signal_score,
        confidence=confidence,
    )
