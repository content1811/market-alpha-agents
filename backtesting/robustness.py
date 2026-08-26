"""Deflated Sharpe Ratio, Probability of Backtest Overfitting, and Minimum
Track Record Length, per docs/plan/section_risk_validation.md section 4 and
Bailey & Lopez de Prado's papers ("The Sharpe Ratio Efficient Frontier", 2012;
"The Deflated Sharpe Ratio", 2014; "The Probability of Backtest Overfitting",
2015/2017 for the CSCV/PBO method).

IMPORTANT: these are graduate-level statistical formulas implemented here from
their published definitions, not from a reference library. Sanity-checked
against directional/monotonicity properties in tests/test_backtesting/
(e.g. "more trials -> lower DSR for the same Sharpe", "genuinely-best variant
-> low PBO", "higher Sharpe -> shorter MinTRL") rather than independently-
sourced exact numeric fixtures, since no authoritative worked numeric example
was available to hand-verify against. Cross-check against a reference
implementation (e.g. the `deflate`/`pbo` PyPI packages) before treating a
go/no-go decision here as final -- flagged per this project's own standard of
not silently presenting an unverified quantitative claim as authoritative.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


def sharpe_ratio(returns: pd.Series, periods_per_year: int = 252, risk_free: float = 0.0) -> float:
    excess = returns - risk_free / periods_per_year
    if excess.std() == 0:
        return 0.0
    return float(excess.mean() / excess.std() * np.sqrt(periods_per_year))


def profit_factor(returns: pd.Series) -> float:
    gains = returns[returns > 0].sum()
    losses = -returns[returns < 0].sum()
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def max_drawdown(equity_curve: pd.Series) -> float:
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    return float(drawdown.min())


def calmar_ratio(returns: pd.Series, periods_per_year: int = 252) -> float:
    equity_curve = (1 + returns).cumprod()
    mdd = max_drawdown(equity_curve)
    if mdd == 0:
        return float("inf") if returns.mean() > 0 else 0.0
    annualized_return = (1 + returns.mean()) ** periods_per_year - 1
    return float(annualized_return / abs(mdd))


def deflated_sharpe_ratio(
    returns: pd.Series,
    num_trials: int,
    trial_sharpe_std: float | None = None,
    periods_per_year: int = 252,
) -> float:
    """DSR per Bailey & Lopez de Prado (2014). Returns the probability
    (in [0,1]) that the observed Sharpe ratio is genuinely positive after
    correcting for (a) the number of parameter/indicator combinations trialed
    and (b) non-normality (skew/kurtosis) of the return series.

    `trial_sharpe_std` is the standard deviation of Sharpe ratios ACROSS all
    trialed variants (not just this one) -- pass it explicitly when available;
    defaults to a conservative 1.0 (annualized-Sharpe-units) placeholder if
    the caller hasn't logged every variant's Sharpe (which the plan requires
    doing, per section_risk_validation.md section 4 point 1 -- this default
    exists so the function doesn't crash before that logging is wired up, not
    because it's a reasonable value to actually rely on).
    """
    T = len(returns)
    if T < 3:
        return 0.0
    sr = sharpe_ratio(returns, periods_per_year=periods_per_year)
    sr_per_period = sr / np.sqrt(periods_per_year)  # DSR's T,skew,kurtosis terms are per-period, not annualized
    skew = float(stats.skew(returns))
    kurt = float(stats.kurtosis(returns, fisher=False))  # non-excess (normal=3), per the standard DSR formula

    sigma_sr = trial_sharpe_std if trial_sharpe_std is not None else 1.0
    euler_mascheroni = 0.5772156649
    if num_trials <= 1:
        sr0_per_period = 0.0
    else:
        z1 = stats.norm.ppf(1 - 1 / num_trials)
        z2 = stats.norm.ppf(1 - 1 / (num_trials * math.e))
        sr0 = sigma_sr * ((1 - euler_mascheroni) * z1 + euler_mascheroni * z2)
        sr0_per_period = sr0 / np.sqrt(periods_per_year)

    denom = np.sqrt(max(1e-12, 1 - skew * sr_per_period + (kurt - 1) / 4 * sr_per_period**2))
    z_stat = (sr_per_period - sr0_per_period) * np.sqrt(T - 1) / denom
    return float(stats.norm.cdf(z_stat))


def minimum_track_record_length(
    returns: pd.Series, benchmark_sharpe: float = 0.0, confidence: float = 0.95, periods_per_year: int = 252
) -> float:
    """MinTRL per Bailey & Lopez de Prado: the minimum number of return
    observations needed for the observed Sharpe to be statistically
    distinguishable from `benchmark_sharpe` at the given confidence level.
    Returns a period count in the SAME frequency as `returns` (e.g. trading
    days if returns are daily) -- convert to calendar time by the caller."""
    sr = sharpe_ratio(returns, periods_per_year=periods_per_year) / np.sqrt(periods_per_year)  # per-period
    sr_bench = benchmark_sharpe / np.sqrt(periods_per_year)
    if sr <= sr_bench:
        return float("inf")  # no amount of history "proves" a non-positive edge
    skew = float(stats.skew(returns))
    kurt = float(stats.kurtosis(returns, fisher=False))
    z = stats.norm.ppf(confidence)
    variance_term = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    return float(1 + variance_term * (z / (sr - sr_bench)) ** 2)


@dataclass
class PBOResult:
    pbo: float
    num_combinations: int
    logits: list[float]


def probability_of_backtest_overfitting(variant_returns: list[pd.Series], num_blocks: int = 10) -> PBOResult:
    """PBO via Combinatorially Symmetric Cross-Validation (CSCV), per Bailey,
    Borwein, Lopez de Prado & Zhu (2015/2017). `variant_returns` is one return
    series PER TRIALED PARAMETER VARIANT (all same length, same index) -- this
    is the "log every variant tested" requirement from
    section_risk_validation.md section 4 point 2, not just the winner.

    Algorithm: split the common index into `num_blocks` contiguous blocks;
    for every way of choosing half the blocks as the in-sample (IS) set and
    the complementary half as out-of-sample (OOS): pick the variant with the
    best IS Sharpe, find its OOS rank among all variants, convert to a logit;
    PBO = fraction of combinations where that logit is <= 0 (the IS "winner"
    performed at or below the OOS median -- a smell of overfitting, not skill).
    """
    n_variants = len(variant_returns)
    if n_variants < 2:
        raise ValueError("PBO requires at least 2 trialed variants to compare")
    if num_blocks % 2 != 0:
        raise ValueError("num_blocks must be even (split into equal IS/OOS halves)")

    length = len(variant_returns[0])
    block_bounds = np.linspace(0, length, num_blocks + 1, dtype=int)
    blocks = [slice(block_bounds[i], block_bounds[i + 1]) for i in range(num_blocks)]

    logits = []
    for is_block_indices in itertools.combinations(range(num_blocks), num_blocks // 2):
        oos_block_indices = [i for i in range(num_blocks) if i not in is_block_indices]

        is_sharpes = []
        oos_sharpes = []
        for variant in variant_returns:
            is_returns = pd.concat([variant.iloc[blocks[i]] for i in is_block_indices])
            oos_returns = pd.concat([variant.iloc[blocks[i]] for i in oos_block_indices])
            is_sharpes.append(sharpe_ratio(is_returns))
            oos_sharpes.append(sharpe_ratio(oos_returns))

        best_is_idx = int(np.argmax(is_sharpes))
        # OOS rank of the IS-winner, as a percentile in (0,1); rank 1=worst.
        oos_rank = sum(1 for s in oos_sharpes if s <= oos_sharpes[best_is_idx])
        omega = oos_rank / (n_variants + 1)
        omega = min(max(omega, 1e-6), 1 - 1e-6)  # avoid +/-inf logit at the boundary
        logit = np.log(omega / (1 - omega))
        logits.append(logit)

    pbo = sum(1 for lg in logits if lg <= 0) / len(logits)
    return PBOResult(pbo=pbo, num_combinations=len(logits), logits=logits)
