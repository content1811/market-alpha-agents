"""Cross-validation test: mean_reversion_signal_series's vectorized formula
must agree with compute_mean_reversion's scalar (latest-bar-only) formula on
the same data -- the cheapest real check that the two didn't drift apart.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from signals.ta.mean_reversion import compute_mean_reversion, mean_reversion_signal_series


def test_vectorized_series_matches_scalar_at_every_truncation_point():
    n = 260
    rng = np.random.RandomState(9)
    closes = pd.Series(100 + np.sin(np.arange(n) / 5) * 3 + rng.normal(0, 0.3, n))
    highs = closes + 0.2
    lows = closes - 0.2

    full_series = mean_reversion_signal_series(highs, lows, closes)

    # spot-check several truncation points: compute_mean_reversion on data
    # truncated to date i should equal the vectorized series at index i.
    for i in [219, 229, 239, 249, 259]:
        scalar_result = compute_mean_reversion(highs.iloc[: i + 1], lows.iloc[: i + 1], closes.iloc[: i + 1])
        assert full_series.iloc[i] == pytest.approx(scalar_result.signal_score, abs=1e-9)
