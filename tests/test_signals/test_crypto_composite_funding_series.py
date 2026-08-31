"""Cross-validation test: crypto_derivatives_funding_signal_series's vectorized
rolling formula must agree with compute_crypto_derivatives's scalar
(latest-print-only) funding_score on the same data -- the cheapest real check
that the two didn't drift apart. Mirrors
tests/test_signals/test_mean_reversion_series.py's truncation-point pattern.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from signals.crypto_composite import compute_crypto_derivatives, crypto_derivatives_funding_signal_series


def test_vectorized_series_matches_scalar_at_every_truncation_point():
    periods_per_day = 3
    z_window_days = 90
    window = periods_per_day * z_window_days  # 270 funding prints

    n = 300
    rng = np.random.RandomState(7)
    funding = pd.Series(rng.normal(0.0001, 0.0003, n))

    full_series = crypto_derivatives_funding_signal_series(
        funding, periods_per_day=periods_per_day, z_window_days=z_window_days
    )

    # spot-check several truncation points once the rolling window is fully
    # warmed up: compute_crypto_derivatives on the trailing `window` prints
    # ending at date i should equal the vectorized series at index i.
    # current_price/prior_price/current_oi/prior_oi are dummy values here --
    # funding_score is computed independently of price/OI in
    # compute_crypto_derivatives, so they cannot affect the comparison.
    for i in [269, 279, 289, 299]:
        trailing_history = funding.iloc[i - window + 1 : i + 1].tolist()
        scalar_result = compute_crypto_derivatives(
            funding_rate_history=trailing_history,
            current_price=100.0,
            prior_price=100.0,
            current_oi=100.0,
            prior_oi=100.0,
            periods_per_day=periods_per_day,
        )
        assert full_series.iloc[i] == pytest.approx(scalar_result.funding_score, abs=1e-9)


def test_series_is_nan_before_window_warms_up():
    periods_per_day = 3
    z_window_days = 90
    window = periods_per_day * z_window_days

    n = 50
    rng = np.random.RandomState(3)
    funding = pd.Series(rng.normal(0.0001, 0.0003, n))
    assert n < window

    full_series = crypto_derivatives_funding_signal_series(
        funding, periods_per_day=periods_per_day, z_window_days=z_window_days
    )
    assert full_series.isna().all()


def test_near_constant_history_stays_finite_and_bounded():
    # Not exactly-zero std -- for a genuinely constant list, np.std/pandas'
    # rolling std both land on a tiny float-accumulation epsilon rather than
    # a mathematically exact 0.0 (verified live: np.std([0.0001]*275*3*365)
    # is ~1.4e-17, not 0.0), so compute_crypto_derivatives' `if std` guard
    # doesn't reliably fire here either -- a pre-existing float-noise quirk
    # of that scalar function, not something this vectorized series should
    # be held to a stricter standard than. What matters for backtesting is
    # that the vectorized series never produces NaN/inf/out-of-range values.
    periods_per_day = 3
    z_window_days = 90
    window = periods_per_day * z_window_days

    constant_funding = pd.Series([0.0001] * (window + 5))
    full_series = crypto_derivatives_funding_signal_series(
        constant_funding, periods_per_day=periods_per_day, z_window_days=z_window_days
    )
    tail = full_series.iloc[window - 1 :]
    assert np.isfinite(tail).all()
    assert ((tail >= -1.0) & (tail <= 1.0)).all()
