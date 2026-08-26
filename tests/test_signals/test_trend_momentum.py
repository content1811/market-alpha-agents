"""Unit tests for signals/ta/trend_momentum.py per the Phase 2 test mandate
in docs/plan/section_orchestration.md section 3: hand-computed fixtures where
exact hand-verification is tractable (SMA/EMA/ATR/trend_confidence), and
directional bounds checks where it is not (ADX's Wilder recursion is well
established but impractical to fully hand-derive here; a monotonic-trend vs.
sideways-chop fixture instead asserts it lands in the textbook-expected range).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from signals.ta.trend_momentum import (
    adx14,
    atr,
    compute_trend_momentum,
    donchian_high,
    ema,
    macd_histogram,
    sma,
    trend_confidence,
)


def test_trend_confidence_matches_corrected_formula():
    # critique.md #5: clip((ADX-15)/10, 0, 1) -- must reach full weight by ADX=25
    assert trend_confidence(10) == 0.0
    assert trend_confidence(15) == 0.0
    assert trend_confidence(20) == pytest.approx(0.5)
    assert trend_confidence(25) == pytest.approx(1.0)
    assert trend_confidence(30) == pytest.approx(1.0)
    assert trend_confidence(40) == pytest.approx(1.0)


def test_sma_hand_computed():
    closes = pd.Series([10.0, 12.0, 14.0, 16.0, 18.0])
    result = sma(closes, window=3)
    # hand: (10+12+14)/3=12, (12+14+16)/3=14, (14+16+18)/3=16
    assert result.iloc[2] == pytest.approx(12.0)
    assert result.iloc[3] == pytest.approx(14.0)
    assert result.iloc[4] == pytest.approx(16.0)


def test_ema_hand_computed():
    closes = pd.Series([10.0, 12.0, 14.0])
    result = ema(closes, window=2)  # span=2 -> alpha = 2/(2+1) = 2/3
    alpha = 2 / 3
    e0 = 10.0
    e1 = alpha * 12.0 + (1 - alpha) * e0
    e2 = alpha * 14.0 + (1 - alpha) * e1
    assert result.iloc[0] == pytest.approx(e0)
    assert result.iloc[1] == pytest.approx(e1)
    assert result.iloc[2] == pytest.approx(e2)


def test_atr_hand_computed():
    # window=3 Wilder smoothing: ewm(alpha=1/3, adjust=False).mean() over true range
    high = pd.Series([10.0, 11.0, 10.5, 12.0, 13.0])
    low = pd.Series([9.0, 9.5, 9.0, 10.0, 11.5])
    close = pd.Series([9.5, 10.5, 9.5, 11.5, 12.5])

    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    tr_values = tr.tolist()
    # tr[0] = high[0]-low[0] = 1.0 (no prev close)
    assert tr_values[0] == pytest.approx(1.0)

    alpha = 1 / 3
    hand_atr = [tr_values[0]]
    for v in tr_values[1:]:
        hand_atr.append(alpha * v + (1 - alpha) * hand_atr[-1])

    result = atr(high, low, close, window=3)
    # atr() sets min_periods=window (consistent with RSI/ADX's own min_periods
    # convention), so the first window-1 values are NaN by design; the
    # underlying ewm recursion itself still starts accumulating from index 0,
    # which is what's being checked from index window-1 onward.
    assert result.iloc[:2].isna().all()
    for i in range(2, len(hand_atr)):
        assert result.iloc[i] == pytest.approx(hand_atr[i]), f"mismatch at index {i}"


def test_donchian_high_excludes_current_bar():
    high = pd.Series([10.0, 12.0, 11.0, 9.0, 8.0])
    result = donchian_high(high, window=3)
    # at index 3: prior 3 bars are indices 0,1,2 -> max(10,12,11)=12
    assert result.iloc[3] == pytest.approx(12.0)
    # at index 4: prior 3 bars are indices 1,2,3 -> max(12,11,9)=12
    assert result.iloc[4] == pytest.approx(12.0)


def test_adx_high_for_strong_monotonic_trend():
    n = 60
    close = pd.Series(100 * (1.01 ** np.arange(n)))  # steady 1%/day uptrend, no noise
    high = close * 1.002
    low = close * 0.998
    result = adx14(high, low, close)
    final_adx = result.iloc[-1]
    assert final_adx > 40, f"expected strong-trend ADX > 40 for a clean monotonic series, got {final_adx}"


def test_adx_low_for_sideways_chop():
    n = 60
    rng = np.random.RandomState(42)
    close = pd.Series(100 + rng.normal(0, 0.3, n).cumsum() * 0 + rng.normal(0, 0.5, n))
    high = close + 0.3
    low = close - 0.3
    result = adx14(high, low, close)
    final_adx = result.iloc[-1]
    assert final_adx < 25, f"expected low ADX for range-bound noise, got {final_adx}"


def test_macd_histogram_positive_for_accelerating_uptrend():
    n = 60
    close = pd.Series(100 * (1.02 ** np.arange(n)))
    hist = macd_histogram(close)
    assert hist.iloc[-1] > 0


def test_compute_trend_momentum_bounds_and_shape():
    n = 300
    rng = np.random.RandomState(7)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.0005, 0.01, n)))
    high = close * 1.005
    low = close * 0.995
    proxy = pd.Series(100 * np.cumprod(1 + rng.normal(0.0003, 0.008, n)))

    result = compute_trend_momentum(high, low, close, proxy)

    for score in (result.ma_score, result.donchian_score, result.xsect_score, result.macd_score, result.signal_score):
        assert -1.0 <= score <= 1.0
    assert 0.0 <= result.trend_confidence <= 1.0
    assert result.adx_value >= 0.0
