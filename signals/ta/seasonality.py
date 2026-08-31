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


def _expanding_bucket_score(n_cum: np.ndarray, sum_cum: np.ndarray, sumsq_cum: np.ndarray, min_n: int = 30, min_abs_t: float = 2.0) -> np.ndarray:
    """Vectorized equivalent of _bucket_score's mean/stdev/t-stat/
    confidence-weight/clip formula, evaluated from pre-accumulated per-index
    (n, sum, sum-of-squares) cumulants instead of re-slicing+recomputing a
    bucket from scratch at every date -- same math, closed form."""
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = sum_cum / n_cum
        var = (sumsq_cum - n_cum * mean**2) / (n_cum - 1)  # sample variance, ddof=1, matches pd.Series.std()
        std = np.sqrt(np.clip(var, 0.0, None))
        t_stat = mean * np.sqrt(n_cum) / std
        confidence_weight = ((n_cum >= min_n) & (np.abs(t_stat) >= min_abs_t)).astype(float)
        score = np.clip((mean / std) * confidence_weight, -1.0, 1.0)
    valid = (n_cum >= 2) & (std > 0) & np.isfinite(std)
    return np.where(valid, score, 0.0)


def _turn_of_month_score_series(daily_returns: pd.Series, dates: pd.Series) -> np.ndarray:
    """Vectorized turn_of_month_score across every date. turn_of_month_score
    is always called by compute_seasonality with data truncated to the
    current as_of row, and its `is_last_day_of_month` mask uses
    `dates.shift(-1)` -- which is NaN on that truncated slice's own last row,
    and `int != NaN` evaluates True in pandas. That means the as_of row's own
    membership in the turn-of-month bucket is unconditionally forced True on
    every call, regardless of true calendar position (verified against the
    scalar function directly) -- a quirk of the scalar formula, not something
    to fix here. Replicated via: real calendar mask accumulated over rows
    [0, i-1] (stable under truncation, since it only ever looks one row
    ahead), plus row i force-included unconditionally.
    """
    dt = pd.to_datetime(dates).reset_index(drop=True)
    ret = np.asarray(daily_returns, dtype=float)

    is_last_day_of_month = (dt.dt.month != dt.shift(-1).dt.month).to_numpy()
    day_index_in_month = dt.groupby(dt.dt.to_period("M")).cumcount().to_numpy()
    is_early_next_month = day_index_in_month < 3
    calendar_mask = is_last_day_of_month | is_early_next_month

    masked_ret = np.where(calendar_mask, ret, 0.0)
    prior_n = np.concatenate([[0.0], np.cumsum(calendar_mask.astype(float))[:-1]])
    prior_sum = np.concatenate([[0.0], np.cumsum(masked_ret)[:-1]])
    prior_sumsq = np.concatenate([[0.0], np.cumsum(masked_ret**2)[:-1]])

    n_cum = prior_n + 1.0
    sum_cum = prior_sum + ret
    sumsq_cum = prior_sumsq + ret**2
    return _expanding_bucket_score(n_cum, sum_cum, sumsq_cum)


def _day_of_week_score_series(daily_returns: pd.Series, dates: pd.Series) -> np.ndarray:
    """Vectorized day_of_week_score across every date: for each date, the
    relevant bucket is that date's own weekday, evaluated on cumulative
    (expanding) stats for that weekday up to and including the date itself --
    no boundary quirk here (unlike TOM), since the mask is a plain weekday
    match, not a next-row shift."""
    ret = np.asarray(daily_returns, dtype=float)
    weekday = pd.to_datetime(dates).dt.weekday.to_numpy()
    score = np.zeros(len(ret))
    for k in range(5):
        mask = weekday == k
        if not mask.any():
            continue
        masked_ret = np.where(mask, ret, 0.0)
        n_cum = np.cumsum(mask.astype(float))
        sum_cum = np.cumsum(masked_ret)
        sumsq_cum = np.cumsum(masked_ret**2)
        bucket = _expanding_bucket_score(n_cum, sum_cum, sumsq_cum)
        score[mask] = bucket[mask]
    return score


def _pead_score_series(
    dates: pd.Series,
    earnings_report_dates: pd.Series,
    earnings_surprise_pct: pd.Series,
    decay_days: int = 90,
) -> np.ndarray:
    """Vectorized pead_score across every date: for each date, uses only
    earnings events reported on or before that date (no look-ahead), finding
    the most recent one and computing the same
    percentile-rank-in-own-history-so-far * time-decay formula pead_score()
    applies to a single as_of date. `earnings_report_dates`/
    `earnings_surprise_pct` are the ticker's full real historical earnings
    events (yfinance get_earnings_dates()), NaN-dropped, any order."""
    events = pd.DataFrame(
        {"report_date": pd.to_datetime(earnings_report_dates), "surprise": np.asarray(earnings_surprise_pct, dtype=float)}
    ).dropna()
    events = events.sort_values("report_date").reset_index(drop=True)

    n_dates = len(dates)
    if events.empty:
        return np.zeros(n_dates)

    # expanding percentile rank of each event's own surprise within all
    # events known up to and including itself -- matches pead_score's
    # `(surprise_pct <= most_recent).mean()`, since `most_recent` there IS
    # the latest known event, included in its own percentile-rank set.
    surprises = events["surprise"].to_numpy()
    sue_pct = np.array([(surprises[: k + 1] <= surprises[k]).mean() for k in range(len(surprises))])

    dates_dt = pd.to_datetime(dates).to_numpy()
    event_dates = events["report_date"].to_numpy()
    idx = np.searchsorted(event_dates, dates_dt, side="right") - 1  # most recent event on/before each date, or -1 if none yet

    known = idx >= 1  # pead_score requires len(surprise_pct)>=2
    clipped_idx = np.clip(idx, 0, len(event_dates) - 1)
    days_since = (dates_dt - event_dates[clipped_idx]).astype("timedelta64[D]").astype(float)
    active = known & (days_since <= decay_days)

    time_decay = np.clip(1.0 - days_since / decay_days, 0.0, None)
    sue_at_idx = sue_pct[clipped_idx]
    pead_vals = np.clip((sue_at_idx * 2 - 1) * time_decay, -1.0, 1.0)

    pead = np.zeros(n_dates)
    pead[active] = pead_vals[active]
    return pead


def seasonality_signal_series(
    daily_returns: pd.Series,
    dates: pd.Series,
    earnings_report_dates: pd.Series | None = None,
    earnings_surprise_pct: pd.Series | None = None,
    pead_decay_days: int = 90,
) -> pd.Series:
    """Vectorized signal_score across every date, for backtesting
    (backtesting/run_backtest.py) -- the same turn-of-month/day-of-week/PEAD
    formula compute_seasonality applies to a single as_of date only, applied
    element-wise to the whole history (each date's own sub-scores use only
    data up to and including that date -- no look-ahead). US-equity scope
    only here: crypto_monthly/halving_cycle sub-scores (is_crypto/is_btc in
    compute_seasonality) are not included, matching this project's only
    seasonality backtest target (AAPL); the raw_avg is the mean of exactly
    [tom_score, dow_score, pead_score], and the +/-0.3 hard cap is applied
    exactly as compute_seasonality does. `earnings_report_dates`/
    `earnings_surprise_pct` are the ticker's real historical earnings events
    (yfinance get_earnings_dates()); pass None for either to zero out PEAD
    entirely (matches compute_seasonality's behavior when no earnings data is
    available)."""
    tom = _turn_of_month_score_series(daily_returns, dates)
    dow = _day_of_week_score_series(daily_returns, dates)

    if earnings_report_dates is not None and earnings_surprise_pct is not None:
        pead = _pead_score_series(dates, earnings_report_dates, earnings_surprise_pct, pead_decay_days)
    else:
        pead = np.zeros(len(daily_returns))

    raw_avg = (tom + dow + pead) / 3.0
    signal_score = np.clip(raw_avg, -0.3, 0.3)
    return pd.Series(signal_score, index=daily_returns.index)


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
