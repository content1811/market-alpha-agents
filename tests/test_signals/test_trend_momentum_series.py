"""Cross-validation test: trend_momentum_signal_series's vectorized formula
must agree with compute_trend_momentum's scalar (latest-bar-only) formula on
the same data -- the cheapest real check that the two didn't drift apart.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from signals.ta.trend_momentum import compute_trend_momentum, trend_momentum_signal_series


def test_vectorized_series_matches_scalar_at_every_truncation_point():
    n = 320
    rng = np.random.RandomState(11)
    closes = pd.Series(100 * np.cumprod(1 + rng.normal(0.0005, 0.01, n)))
    highs = closes * 1.005
    lows = closes * 0.995
    proxy = pd.Series(100 * np.cumprod(1 + rng.normal(0.0003, 0.008, n)))

    full_series = trend_momentum_signal_series(highs, lows, closes, proxy)

    # spot-check several truncation points: compute_trend_momentum on data
    # truncated to date i should equal the vectorized series at index i.
    for i in [269, 279, 289, 299, 319]:
        scalar_result = compute_trend_momentum(
            highs.iloc[: i + 1], lows.iloc[: i + 1], closes.iloc[: i + 1], proxy.iloc[: i + 1]
        )
        assert full_series.iloc[i] == pytest.approx(scalar_result.signal_score, abs=1e-9)
