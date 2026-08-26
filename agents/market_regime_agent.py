"""MarketRegimeAgent per docs/plan/section_agents.md section 11.

No LLM call: the plan's own output schema for this agent has no rationale
field, only numbers -- there's nothing for an LLM to interpret. Runs once per
asset class per cycle, not once per ticker (see module docstring in
signals/market_regime.py).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from agents.schemas import MarketRegimeVerdict
from data.schema import AssetClass, DataQualityFlag, NormalizedBar
from signals.market_regime import compute_market_regime

# Per section_agents.md section 11: SPY for US, TOPIX/Nikkei-linked proxy for
# JP, BTC (or a cap-weighted basket) for crypto -- the same broad-market
# proxies TrendMomentumAgent uses for cross-sectional momentum.
PROXY_BY_ASSET_CLASS = {
    AssetClass.US_EQUITY: "SPY",
    AssetClass.JP_EQUITY: "^TOPX",
    AssetClass.CRYPTO: "BTC/USDT",
}


def build_verdict(
    asset_class: AssetClass,
    proxy_bars: list[NormalizedBar],
    breaker_percentile: float = 85.0,
    breaker_multiplier: float = 0.5,
) -> MarketRegimeVerdict:
    if not proxy_bars:
        raise ValueError(f"no proxy bars provided for {asset_class.value}")

    df = pd.DataFrame([b.model_dump() for b in proxy_bars]).sort_values("ts_utc")
    daily_returns = df["close"].pct_change().dropna()
    data_quality_flag = proxy_bars[-1].data_quality_flag

    result = compute_market_regime(
        daily_returns, breaker_percentile=breaker_percentile, breaker_multiplier=breaker_multiplier
    )

    multiplier = result.position_size_ceiling_multiplier
    if data_quality_flag == DataQualityFlag.STALE:
        # a stale regime read shouldn't claim confident "all clear" -- fall
        # back to the de-risked multiplier rather than trusting a possibly
        # outdated calm reading (never loosen sizing on stale data).
        multiplier = min(multiplier, breaker_multiplier)

    return MarketRegimeVerdict(
        asset_class=asset_class,
        as_of_timestamp=datetime.now(timezone.utc),
        vol_percentile=result.vol_percentile,
        regime_breaker_active=result.regime_breaker_active,
        position_size_ceiling_multiplier=multiplier,
        data_quality_flag=data_quality_flag,
    )
