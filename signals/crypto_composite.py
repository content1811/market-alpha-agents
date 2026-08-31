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
import pandas as pd

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


def crypto_derivatives_funding_signal_series(
    funding_rate_history: pd.Series,
    periods_per_day: int = 3,
    z_window_days: int = 90,
) -> pd.Series:
    """Vectorized funding_score across every funding print, for backtesting
    (backtesting/run_backtest.py) -- the same contrarian z-score formula
    compute_crypto_derivatives applies to the latest print only (mean/std of
    whatever `funding_rate_history` list the caller passes in), applied here
    as a rolling trailing-90-day window per section_agents.md section 7
    indicator #1 ("z-score vs trailing 90-day history"), element-wise across
    the whole history. `funding_rate_history` must be indexed by funding-print
    timestamp at `periods_per_day` prints/day (Binance USDT-margined
    perpetuals: every 8h, so periods_per_day=3 -- verified live against
    ccxt's fetch_funding_rate_history). Uses population std (ddof=0), matching
    compute_crypto_derivatives' np.std, not pandas' default sample std.

    oi_score/skew_score are deliberately NOT part of this series -- Binance's
    public open-interest-history endpoint was verified live to reject any
    `since` older than ~30-45 days ("startTime is invalid"), nowhere near the
    252+63-day window walk_forward_backtest needs for even one split, and
    skew_z=None is already CryptoDerivativesAgent's live-agent default (no
    wired Deribit source). This backtests funding_score alone, same
    excluded-sub-component honesty as skew_z's treatment in
    compute_crypto_derivatives, not a full signal_score reconstruction.
    """
    window = periods_per_day * z_window_days
    annualized = funding_rate_history * periods_per_day * 365
    mean = annualized.rolling(window=window).mean()
    std = annualized.rolling(window=window).std(ddof=0)
    funding_z = ((annualized - mean) / std).where(std != 0, 0.0)
    return (-funding_z / 2).clip(-1.0, 1.0)


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
    excluded: list[str]
    signal_score: float
    confidence: float


# section_agents.md section 6's weighted_avg weights. Each maps to the
# indicator that can be individually excluded (unlock_penalty is the one
# exception -- see compute_onchain's docstring).
ONCHAIN_WEIGHTS = {"mvrv": 0.30, "sopr": 0.20, "flow": 0.20, "whale": 0.15, "addr_divergence": 0.05, "unlock": 0.10}


def addr_divergence_flag_score(active_address_pct_change: float, price_making_new_high: bool) -> float:
    """Indicator #5, "divergence-only filter": section_agents.md section 6
    only assigns a score to two specific configurations (price at a new high
    while addresses decline = bearish flag; both rising = bullish
    confirmation) -- every other combination is explicitly out of scope for
    this indicator, not a continuum, so it returns a flat 0.0 rather than an
    interpolated value. Fixed magnitudes (not a formula) per the plan's own
    point-scale language ("-5 to -10" / "+5"), same documented-judgment-call
    treatment as compute_crypto_derivatives' OI_SCORE_MAP."""
    addresses_rising = active_address_pct_change > 0
    if price_making_new_high and not addresses_rising:
        return -7.5
    if price_making_new_high and addresses_rising:
        return 5.0
    return 0.0


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
    mvrv: float | None,
    sopr_score: float | None,
    flow_score: float | None,
    whale_score: float | None,
    addr_divergence_score: float | None,
    unlock_penalty: float,
) -> CryptoOnChainSubScores:
    """Implements section_agents.md section 6's signal_score computation:
    onchain_raw = weighted_avg(mvrv_pctile:0.30, sopr:0.20, flow:0.20,
    whale:0.15, addr_divergence:0.05, unlock_penalty:0.10); signal_score =
    clip(onchain_raw/100, -1, 1). All inputs except mvrv are already on the
    0-100-style composite scale the plan uses.

    mvrv/sopr_score/flow_score/whale_score/addr_divergence_score may each be
    None -- per section 6's own note, no free, live, ready-made source exists
    for MVRV/SOPR at all (real realized-cap/UTXO-cost-basis computation is a
    "real engineering lift", not an API call), and flow/whale/addr_divergence
    are only computable once agents/crypto_on_chain_agent.py's local
    balance-snapshot ledger (Etherscan) or its Dune active-address query have
    accumulated enough history. A None input is excluded from the weighted
    average and its weight redistributed away (mirroring
    compute_crypto_derivatives' skew_weight pattern) rather than guessed at a
    neutral value -- confidence scales down with however much of the full
    weighting scheme is actually backed by real data, capped at the section 6
    ceiling of 0.6 when everything is available.

    unlock_penalty has no such gap for BTC/ETH -- there's no vesting
    schedule to look up, so 0.0 is the correct value, not a placeholder for
    missing data -- and is therefore required and always counted at full
    weight. (Altcoin unlock-calendar wiring, e.g. via DefiLlama, is a
    documented future gap, same treatment as CryptoDerivativesAgent's
    unwired Deribit skew.)
    """
    weighted_sum = 0.0
    total_weight = 0.0
    excluded: list[str] = []

    mvrv_pctile = mvrv_band_score(mvrv) if mvrv is not None else None
    for key, value in (
        ("mvrv", mvrv_pctile),
        ("sopr", sopr_score),
        ("flow", flow_score),
        ("whale", whale_score),
        ("addr_divergence", addr_divergence_score),
    ):
        if value is None:
            excluded.append(key)
            continue
        weighted_sum += ONCHAIN_WEIGHTS[key] * value
        total_weight += ONCHAIN_WEIGHTS[key]

    weighted_sum += ONCHAIN_WEIGHTS["unlock"] * unlock_penalty
    total_weight += ONCHAIN_WEIGHTS["unlock"]

    signal_score = float(np.clip(weighted_sum / total_weight / 100, -1.0, 1.0)) if total_weight else 0.0
    confidence = 0.6 * total_weight  # capped per section_agents.md section 6, further scaled by data availability

    return CryptoOnChainSubScores(
        mvrv_score=mvrv_pctile if mvrv_pctile is not None else 0.0,
        sopr_score=sopr_score if sopr_score is not None else 0.0,
        flow_score=flow_score if flow_score is not None else 0.0,
        whale_score=whale_score if whale_score is not None else 0.0,
        addr_divergence_score=addr_divergence_score if addr_divergence_score is not None else 0.0,
        unlock_penalty=unlock_penalty,
        excluded=excluded,
        signal_score=signal_score,
        confidence=confidence,
    )
