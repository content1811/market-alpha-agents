"""Pure-math market-regime breaker for MarketRegimeAgent, per
docs/plan/section_agents.md section 11. No LLM calls -- this agent's own
output schema has no rationale field, only numbers.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def realized_volatility(daily_returns: pd.Series, window: int = 20) -> pd.Series:
    """Trailing N-day annualized realized volatility."""
    return daily_returns.rolling(window=window).std() * np.sqrt(252)


def percentile_rank(value: float, distribution: pd.Series) -> float:
    """Percentile rank of `value` within `distribution`, in [0, 100]."""
    clean = distribution.dropna()
    if len(clean) == 0:
        return 50.0
    return float((clean <= value).mean() * 100)


@dataclass
class MarketRegimeResult:
    vol_percentile: float
    regime_breaker_active: bool
    position_size_ceiling_multiplier: float


def compute_market_regime(
    daily_returns: pd.Series,
    window: int = 20,
    trailing_days: int = 252,
    breaker_percentile: float = 85.0,
    breaker_multiplier: float = 0.5,
) -> MarketRegimeResult:
    """vol_percentile = percentile_rank(current 20d realized vol, trailing 1yr
    distribution of that same rolling series); if >= breaker_percentile
    (default 85th), halve (default 0.5) the position-size ceiling -- per
    section_agents.md section 11's concrete rule, verbatim."""
    vol_series = realized_volatility(daily_returns, window)
    current_vol = vol_series.iloc[-1]
    trailing_distribution = vol_series.tail(trailing_days)

    vol_pctile = percentile_rank(current_vol, trailing_distribution)
    breaker_active = vol_pctile >= breaker_percentile
    multiplier = breaker_multiplier if breaker_active else 1.0

    return MarketRegimeResult(
        vol_percentile=vol_pctile,
        regime_breaker_active=breaker_active,
        position_size_ceiling_multiplier=multiplier,
    )
