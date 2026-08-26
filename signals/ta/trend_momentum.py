"""Pure-math trend/momentum signals for TrendMomentumAgent, per
docs/plan/section_agents.md section 2. No LLM calls here -- these are plain
functions over price series, unit-tested against fixed fixtures.

ADX/trend_confidence is also the shared regime gate consumed by
MeanReversionAgent (section_agents.md section 1, rule 5), so it lives here as
the single implementation both signal modules import.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from ta.trend import ADXIndicator, MACD


def sma(closes: pd.Series, window: int) -> pd.Series:
    return closes.rolling(window=window).mean()


def ema(closes: pd.Series, window: int) -> pd.Series:
    return closes.ewm(span=window, adjust=False).mean()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    # Wilder's smoothing (same recursive form as ADX below), matching the
    # atr_multiple stop-loss convention used throughout section_agents.md.
    return true_range.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()


def adx14(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    return ADXIndicator(high, low, close, window=window).adx()


def trend_confidence(adx: float) -> float:
    """clip((ADX-15)/10, 0, 1) -- corrected formula per critique.md #5.
    trend_confidence(20)=0.5, (25)=1.0, (30)=1.0, (40)=1.0, matching
    TrendMomentumAgent's '>25 = trending, full weight' threshold exactly."""
    return float(np.clip((adx - 15) / 10, 0.0, 1.0))


def donchian_high(high: pd.Series, window: int = 20) -> pd.Series:
    # shift(1): "prior N-day high", excludes today's own bar per section_agents.md's
    # donchian_score = clip((price - prior_N_high) / ATR14, ...)
    return high.rolling(window=window).max().shift(1)


def macd_histogram(closes: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    return MACD(closes, window_fast=fast, window_slow=slow, window_sign=signal).macd_diff()


@dataclass
class TrendMomentumSubScores:
    ma_score: float
    donchian_score: float
    xsect_score: float
    macd_score: float
    trend_confidence: float
    adx_value: float
    signal_score: float


def compute_trend_momentum(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    proxy_close: pd.Series,
    fast_ma_window: int = 20,
    slow_ma_window: int = 50,
    donchian_window: int = 20,
    xsect_lookback_days: int = 252,
) -> TrendMomentumSubScores:
    """Implements section_agents.md section 2's signal_score computation
    verbatim. `proxy_close` is the broad-market benchmark series (SPY/TOPIX/BTC)
    aligned to the same dates as `close` -- see critique.md #11 for why this
    replaced a watchlist-percentile-rank design."""
    atr14 = atr(high, low, close).iloc[-1]
    if atr14 == 0 or pd.isna(atr14):
        raise ValueError("ATR14 is zero/NaN -- cannot normalize scores")

    fast = sma(close, fast_ma_window).iloc[-1]
    slow = sma(close, slow_ma_window).iloc[-1]
    ma_score = float(np.clip((fast - slow) / atr14, -1.0, 1.0))

    prior_high = donchian_high(high, donchian_window).iloc[-1]
    donchian_score = float(np.clip((close.iloc[-1] - prior_high) / atr14, -1.0, 1.0)) if close.iloc[-1] > prior_high else 0.0

    ticker_return = close.iloc[-1] / close.iloc[-xsect_lookback_days] - 1
    proxy_return = proxy_close.iloc[-1] / proxy_close.iloc[-xsect_lookback_days] - 1
    excess_return = ticker_return - proxy_return
    xsect_score = float(np.clip(excess_return / 0.5, -1.0, 1.0))

    hist = macd_histogram(close).iloc[-1]
    macd_score = float(np.clip(hist / atr14, -1.0, 1.0)) + (0.1 if hist > 0 else -0.1)
    macd_score = float(np.clip(macd_score, -1.0, 1.0))

    adx_value = float(adx14(high, low, close).iloc[-1])
    tc = trend_confidence(adx_value)

    raw = 0.3 * ma_score + 0.25 * donchian_score + 0.3 * xsect_score + 0.15 * macd_score
    signal_score = tc * raw

    return TrendMomentumSubScores(
        ma_score=ma_score,
        donchian_score=donchian_score,
        xsect_score=xsect_score,
        macd_score=macd_score,
        trend_confidence=tc,
        adx_value=adx_value,
        signal_score=float(np.clip(signal_score, -1.0, 1.0)),
    )
