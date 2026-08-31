"""Cross-validation test: seasonality_signal_series's vectorized formula must
agree with compute_seasonality's scalar (single-as_of-date) formula on the
same data -- the cheapest real check that the two didn't drift apart.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from signals.ta.seasonality import compute_seasonality, seasonality_signal_series


def _surprise_history_as_of(report_dates: pd.DatetimeIndex, surprise: pd.Series, as_of: pd.Timestamp):
    """Mirrors what SeasonalityAgent derives from yf.Ticker.get_earnings_dates()
    for a given as_of date: only events known by then, most-recent-first, plus
    days since the most recent one."""
    known = report_dates <= as_of
    if not known.any():
        return None, None
    sub_dates = report_dates[known]
    sub_surprise = surprise[known]
    order = np.argsort(-sub_dates.astype("int64"))
    history = sub_surprise.iloc[order].reset_index(drop=True)
    days_since = (as_of - sub_dates.max()).days
    return history, days_since


def test_vectorized_series_matches_scalar_at_every_truncation_point():
    n = 900
    rng = np.random.RandomState(21)
    dates = pd.Series(pd.date_range("2018-01-01", periods=n, freq="B"))
    returns = pd.Series(rng.normal(0.0002, 0.01, n))

    report_dates = pd.DatetimeIndex(pd.date_range("2018-02-15", periods=20, freq="91D"))
    surprise = pd.Series(rng.normal(0, 5, len(report_dates)))

    full_series = seasonality_signal_series(returns, dates, report_dates, surprise)

    # spot-check several truncation points: compute_seasonality on data
    # truncated to date i should equal the vectorized series at index i.
    for i in [219, 379, 559, 739, 899]:
        as_of_ts = dates.iloc[i]
        history, days_since = _surprise_history_as_of(report_dates, surprise, as_of_ts)
        scalar_result = compute_seasonality(
            returns.iloc[: i + 1].reset_index(drop=True),
            dates.iloc[: i + 1].reset_index(drop=True),
            as_of=as_of_ts.date(),
            surprise_pct_history=history,
            days_since_earnings=days_since,
        )
        assert full_series.iloc[i] == pytest.approx(scalar_result.signal_score, abs=1e-9)
