"""Pure-math mean-reversion signals for MeanReversionAgent, per
docs/plan/section_agents.md section 1. No LLM calls here.

Note on scope: the ADF/half-life stationarity check mentioned in section 1
("further reduced... if the ADF/half-life check indicates non-mean-reverting
behavior") is NOT implemented here yet -- the plan frames it as an additional
confidence reducer on top of the mandatory ADX regime gate (which IS
implemented below), not a replacement for it. Deferred as a follow-up
refinement; the ADX gate alone is what makes this agent's score computation
correct today.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from ta.volatility import BollingerBands

from signals.ta.trend_momentum import adx14, sma, trend_confidence


def bollinger_pct_b(closes: pd.Series, window: int = 20, k: float = 2.0) -> pd.Series:
    return BollingerBands(closes, window=window, window_dev=k).bollinger_pband()


def bollinger_bandwidth(closes: pd.Series, window: int = 20, k: float = 2.0) -> pd.Series:
    return BollingerBands(closes, window=window, window_dev=k).bollinger_wband()


def bollinger_bands(closes: pd.Series, window: int = 20, k: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (lower, mid, upper) band series -- used for structure-based
    stop_loss/profit_target levels, per section_agents.md section 1 Output
    specifics ('mid-band/VWAP/moving average being reverted to')."""
    bb = BollingerBands(closes, window=window, window_dev=k)
    return bb.bollinger_lband(), bb.bollinger_mavg(), bb.bollinger_hband()


def rsi2(closes: pd.Series, window: int = 2) -> pd.Series:
    diff = closes.diff(1)
    up = diff.where(diff > 0, 0.0)
    down = -diff.where(diff < 0, 0.0)
    avg_up = up.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_down = down.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_up / avg_down
    return pd.Series(np.where(avg_down == 0, 100.0, 100 - 100 / (1 + rs)), index=closes.index)


def zscore_vs_ma(closes: pd.Series, window: int = 20) -> pd.Series:
    ma = sma(closes, window)
    std = closes.rolling(window=window).std()
    return (closes - ma) / std


def vwap_zscore(prices: pd.Series, volumes: pd.Series) -> float:
    """Session-scoped intraday VWAP z-score: z=(price-VWAP)/intraday_stdev.
    `prices`/`volumes` must already be sliced to a single session, with the
    first/last 15 minutes excluded by the caller per section_agents.md #1.3."""
    vwap = (prices * volumes).sum() / volumes.sum()
    stdev = prices.std()
    if stdev == 0 or pd.isna(stdev):
        return 0.0
    return float((prices.iloc[-1] - vwap) / stdev)


@dataclass
class MeanReversionSubScores:
    bb_score: float
    rsi2_score: float
    z_score: float
    vwap_score: float | None
    trend_confidence: float
    adx_value: float
    signal_score: float
    confidence: float


def compute_mean_reversion(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    bb_window: int = 20,
    bb_k: float = 2.0,
    z_window: int = 20,
    sma200_window: int = 200,
    vwap_z: float | None = None,
) -> MeanReversionSubScores:
    """Implements section_agents.md section 1's signal_score computation
    verbatim, including the corrected trend_confidence regime gate."""
    n = len(close)

    pct_b = bollinger_pct_b(close, bb_window, bb_k).iloc[-1]
    bb_score = float(np.clip(-(2 * pct_b - 1), -1.0, 1.0))

    rsi2_val = rsi2(close).iloc[-1]
    price = close.iloc[-1]
    sma200 = sma(close, sma200_window).iloc[-1] if n >= sma200_window else np.nan
    if not pd.isna(sma200) and price > sma200:
        rsi2_score = float(np.clip((50 - rsi2_val) / 50, -1.0, 1.0))
    else:
        rsi2_score = 0.0

    z_ma = zscore_vs_ma(close, z_window).iloc[-1]
    z_score = float(np.clip(-z_ma / 2, -1.0, 1.0))

    vwap_score = float(np.clip(-vwap_z / 2, -1.0, 1.0)) if vwap_z is not None else None

    if vwap_score is not None:
        raw_score = 0.3 * bb_score + 0.3 * rsi2_score + 0.3 * z_score + 0.1 * vwap_score
    else:
        # redistribute the 0.1 VWAP weight evenly across the three swing sub-scores
        raw_score = (1 / 3) * bb_score + (1 / 3) * rsi2_score + (1 / 3) * z_score

    adx_value = float(adx14(high, low, close).iloc[-1])
    tc = trend_confidence(adx_value)

    signal_score = float(np.clip(raw_score * (1 - tc), -1.0, 1.0))

    confidence = 1 - tc
    if n < 30:
        confidence -= 0.3
    confidence = float(np.clip(confidence, 0.0, 1.0))

    return MeanReversionSubScores(
        bb_score=bb_score,
        rsi2_score=rsi2_score,
        z_score=z_score,
        vwap_score=vwap_score,
        trend_confidence=tc,
        adx_value=adx_value,
        signal_score=signal_score,
        confidence=confidence,
    )
