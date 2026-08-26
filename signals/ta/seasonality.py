"""Pure-math seasonality signals for SeasonalityAgent, per
docs/plan/section_agents.md section 3. No LLM calls here.

Scope note: sector intramonth cycle (indicator #3) is NOT implemented -- it
needs a tracked sector-ETF universe this system doesn't configure yet, and the
plan itself flags it as "very low-weight" even when available. PEAD/SUE here
uses yfinance's earnings Surprise(%) directly as a simplified SUE proxy
(properly standardizing it against each ticker's own historical surprise
stdev is a further refinement, not done here) -- documented, not hidden.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

# Public, well-documented BTC halving dates (block height 210000-multiples).
BTC_HALVING_DATES = [
    date(2012, 11, 28),
    date(2016, 7, 9),
    date(2020, 5, 11),
    date(2024, 4, 20),
]
BTC_AVG_CYCLE_DAYS = 1460  # ~4 years


def _bucket_score(bucket_returns: pd.Series, min_n: int = 30, min_abs_t: float = 2.0) -> tuple[float, int, float]:
    """score = clip((bucket_mean/bucket_stdev)*confidence_weight, -1, 1),
    confidence_weight -> 0 if n<min_n or |t|<min_abs_t. Returns (score, n, t_stat)."""
    n = len(bucket_returns)
    if n < 2:
        return 0.0, n, 0.0
    mean = bucket_returns.mean()
    std = bucket_returns.std()
    if std == 0 or pd.isna(std):
        return 0.0, n, 0.0
    t_stat = mean / (std / np.sqrt(n))
    confidence_weight = 1.0 if (n >= min_n and abs(t_stat) >= min_abs_t) else 0.0
    score = float(np.clip((mean / std) * confidence_weight, -1.0, 1.0))
    return score, n, float(t_stat)


def turn_of_month_score(daily_returns: pd.Series, dates: pd.Series) -> tuple[float, int, float]:
    """Turn-of-month window: last trading day of month through 3rd trading
    day of the next month, per section_agents.md section 3 indicator #1."""
    dates = pd.to_datetime(dates)
    df = pd.DataFrame({"ret": daily_returns.values, "date": dates.values})
    df["is_month_end"] = df["date"].dt.is_month_end | (
        df["date"].shift(-1).dt.month != df["date"].dt.month
    )
    df["day_index_in_month"] = df.groupby(df["date"].dt.to_period("M")).cumcount()
    # flag: last trading day of the month, OR one of the first 3 trading days of next month
    is_last_day_of_month = df["date"].dt.month != df["date"].shift(-1).dt.month
    is_early_next_month = df["day_index_in_month"] < 3
    mask = is_last_day_of_month | is_early_next_month
    return _bucket_score(df.loc[mask, "ret"])


def day_of_week_score(daily_returns: pd.Series, dates: pd.Series, weekday: int) -> tuple[float, int, float]:
    """Same bucket-score formula applied to a single ISO weekday (0=Monday)."""
    dates = pd.to_datetime(dates)
    mask = dates.dt.weekday.values == weekday
    return _bucket_score(daily_returns[mask])


def pead_score(surprise_pct: pd.Series, days_since_earnings: int, decay_days: int = 90) -> float:
    """SUE-proxy percentile rank * time_decay, per section_agents.md section 3
    indicator #2. `surprise_pct` is the ticker's own historical Surprise(%)
    series (yfinance get_earnings_dates()); the most recent value's percentile
    rank within that history stands in for a properly standardized SUE."""
    if len(surprise_pct) < 2 or days_since_earnings > decay_days:
        return 0.0
    most_recent = surprise_pct.iloc[0]  # yfinance returns most-recent-first
    sue_pct = (surprise_pct <= most_recent).mean()  # percentile rank in [0,1]
    time_decay = max(0.0, 1 - days_since_earnings / decay_days)
    return float(np.clip((sue_pct * 2 - 1) * time_decay, -1.0, 1.0))


def crypto_monthly_seasonality_score(daily_returns: pd.Series, dates: pd.Series, current_month: int) -> tuple[float, int]:
    """6-8yr historical mean return by calendar month, z-scored, capped at
    +/-5 points (0.05) contribution per section_agents.md section 3 indicator #4."""
    dates = pd.to_datetime(dates)
    monthly_returns = pd.DataFrame({"ret": daily_returns.values, "month": dates.dt.month.values})
    bucket = monthly_returns.loc[monthly_returns["month"] == current_month, "ret"]
    n = len(bucket)
    if n < 2 or bucket.std() == 0:
        return 0.0, n
    z = bucket.mean() / bucket.std()
    return float(np.clip(z, -0.05, 0.05)), n


def halving_cycle_phase(as_of: date, halving_dates: list[date] = BTC_HALVING_DATES) -> tuple[str, float]:
    """Label-only phase tag (BTC only), capped at +/-0.05 contribution, per
    section_agents.md section 3 indicator #5."""
    past_halvings = [d for d in halving_dates if d <= as_of]
    if not past_halvings:
        return "pre-halving-data", 0.0
    last_halving = max(past_halvings)
    days_since = (as_of - last_halving).days
    cycle_fraction = days_since / BTC_AVG_CYCLE_DAYS
    if cycle_fraction < 0.25:
        return "early-post-halving", 0.05  # historically bullish-tilted phase, low confidence
    if cycle_fraction < 0.75:
        return "mid-cycle", 0.0
    return "late-cycle", -0.03  # historically more caution-tilted, still low confidence


def turn_of_quarter_volatility_flag(as_of: date) -> bool:
    """Indicator #6: does not set a directional score -- sets a caution flag
    for RiskManagerAgent to widen stops / reduce size."""
    is_quarter_month = as_of.month in (3, 6, 9, 12)
    return is_quarter_month and as_of.day >= 25


@dataclass
class SeasonalitySubScores:
    turn_of_month_score: float
    turn_of_month_n: int
    day_of_week_score: float
    day_of_week_n: int
    pead_score: float
    crypto_monthly_score: float | None
    halving_phase: str | None
    halving_score: float
    volatility_caution: bool
    signal_score: float
    confidence: float


def compute_seasonality(
    daily_returns: pd.Series,
    dates: pd.Series,
    as_of: date,
    surprise_pct_history: pd.Series | None = None,
    days_since_earnings: int | None = None,
    is_crypto: bool = False,
    is_btc: bool = False,
) -> SeasonalitySubScores:
    tom_score, tom_n, _ = turn_of_month_score(daily_returns, dates)
    dow_score, dow_n, _ = day_of_week_score(daily_returns, dates, weekday=as_of.weekday())

    pead = 0.0
    if surprise_pct_history is not None and days_since_earnings is not None:
        pead = pead_score(surprise_pct_history, days_since_earnings)

    crypto_score = None
    active_scores = [tom_score, dow_score, pead]
    if is_crypto:
        crypto_score, _ = crypto_monthly_seasonality_score(daily_returns, dates, as_of.month)
        active_scores.append(crypto_score)

    halving_phase, halving_score = None, 0.0
    if is_btc:
        halving_phase, halving_score = halving_cycle_phase(as_of)
        active_scores.append(halving_score)

    volatility_caution = turn_of_quarter_volatility_flag(as_of)

    raw_avg = float(np.mean(active_scores)) if active_scores else 0.0
    signal_score = float(np.clip(raw_avg, -0.3, 0.3))  # system-enforced cap, section_agents.md section 3

    sample_size = min(tom_n, dow_n) if (tom_n and dow_n) else max(tom_n, dow_n)
    size_confidence = float(np.clip(sample_size / 60, 0.0, 1.0))  # heuristic scaling toward the hard cap
    confidence = min(size_confidence, 0.5)  # hard cap per section_agents.md section 3

    return SeasonalitySubScores(
        turn_of_month_score=tom_score,
        turn_of_month_n=tom_n,
        day_of_week_score=dow_score,
        day_of_week_n=dow_n,
        pead_score=pead,
        crypto_monthly_score=crypto_score,
        halving_phase=halving_phase,
        halving_score=halving_score,
        volatility_caution=volatility_caution,
        signal_score=signal_score,
        confidence=confidence,
    )
