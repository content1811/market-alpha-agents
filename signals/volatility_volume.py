"""Pure-math volatility/volume signals for VolatilityVolumeAgent, per
docs/plan/section_agents.md section 5. No LLM calls here.

Note on scope: Point-of-Control here is approximated from daily-bar
volume-at-typical-price binning, not true intraday volume-by-price (which
needs intraday bars we don't have yet). The plan frames intraday POC as
"where available" -- this is the daily-bar fallback, not the full design.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from signals.ta.trend_momentum import atr


def atr_series(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    return atr(high, low, close, window)


def rvol(volume: pd.Series, lookback: int = 20) -> pd.Series:
    """Relative volume: today's volume / trailing lookback-day average
    (excluding today itself)."""
    avg_volume = volume.shift(1).rolling(window=lookback).mean()
    return volume / avg_volume


def point_of_control(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, bins: int = 20) -> float:
    """Daily-bar POC approximation: bin each day's typical price
    ((H+L+C)/3) and accumulate that day's volume into its bin; POC is the
    bin midpoint with the most accumulated volume."""
    typical_price = (high + low + close) / 3
    price_min, price_max = typical_price.min(), typical_price.max()
    if price_max == price_min:
        return float(price_min)
    bin_edges = np.linspace(price_min, price_max, bins + 1)
    bin_indices = np.clip(np.digitize(typical_price, bin_edges) - 1, 0, bins - 1)
    volume_by_bin = np.zeros(bins)
    for idx, vol in zip(bin_indices, volume):
        volume_by_bin[idx] += vol
    poc_bin = int(np.argmax(volume_by_bin))
    return float((bin_edges[poc_bin] + bin_edges[poc_bin + 1]) / 2)


@dataclass
class VolatilityVolumeSubScores:
    vol_expansion_score: float
    rvol_score: float
    distance_score: float
    vol_conf_multiplier: float
    signal_score: float
    atr14: float
    rvol_value: float
    confidence: float


def compute_volatility_volume(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    atr_lookback: int = 14,
    atr_avg_lookback: int = 60,
    rvol_lookback: int = 20,
) -> VolatilityVolumeSubScores:
    """Implements section_agents.md section 5's signal_score computation
    verbatim, including the direction-agnostic-magnitude-signed-by-return
    convention and the exported vol_conf_multiplier."""
    atr_vals = atr_series(high, low, close, atr_lookback)
    atr14 = float(atr_vals.iloc[-1])
    atr_avg_60d = float(atr_vals.tail(atr_avg_lookback).mean())
    vol_expansion_score = float(np.clip((atr14 / atr_avg_60d) - 1, -1.0, 1.0)) if atr_avg_60d else 0.0

    rvol_vals = rvol(volume, rvol_lookback)
    rvol_value = float(rvol_vals.iloc[-1])
    rvol_score = float(np.clip((rvol_value - 1) / 4, 0.0, 1.0))

    poc = point_of_control(high, low, close, volume)
    distance_score = float(np.clip((close.iloc[-1] - poc) / atr14, -1.0, 1.0)) if atr14 else 0.0

    vol_conf_multiplier = 0.5 + 0.5 * ((vol_expansion_score + rvol_score) / 2)

    recent_return = close.iloc[-1] / close.iloc[-2] - 1 if len(close) >= 2 else 0.0
    direction = 1.0 if recent_return >= 0 else -1.0
    magnitude = float(np.clip((abs(vol_expansion_score) + rvol_score) / 2, 0.0, 1.0))
    signal_score = direction * magnitude

    # confidence: high when the two proxies agree in magnitude, reduced on disagreement
    disagreement = abs(abs(vol_expansion_score) - rvol_score)
    confidence = float(np.clip(1.0 - disagreement, 0.0, 1.0))

    return VolatilityVolumeSubScores(
        vol_expansion_score=vol_expansion_score,
        rvol_score=rvol_score,
        distance_score=distance_score,
        vol_conf_multiplier=vol_conf_multiplier,
        signal_score=signal_score,
        atr14=atr14,
        rvol_value=rvol_value,
        confidence=confidence,
    )
