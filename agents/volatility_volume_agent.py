"""VolatilityVolumeAgent per docs/plan/section_agents.md section 5.

Unusual among the specialists: its main system role is exporting
vol_conf_multiplier and the raw ATR14 for every other agent to consume, not
its own directional call. Score/confidence still come entirely from code;
the LLM writes only the rationale.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from pydantic import BaseModel, Field

from agents.llm_client import call_structured
from agents.schemas import AgentVerdict, HoldingPeriod, ProfitTarget, StopLoss
from data.schema import AssetClass, DataQualityFlag, NormalizedBar
from signals.volatility_volume import compute_volatility_volume

SYSTEM_PROMPT = """You are a market-microstructure/volume specialist, deliberately \
"boring" and mechanical -- you almost never editorialize about direction, only about \
participation/conviction. You are the rationale-writer for VolatilityVolumeAgent in a \
local trading-research system.

You will be given already-computed sub-scores and the raw ATR14/RVOL numbers. Write \
ONLY the rationale field -- you do not set the score or confidence.

Rules for the rationale (<=280 chars):
1. Volume/volatility alone never implies direction -- phrase your output as "confirms" \
or "does not confirm" another signal, never as an independent buy/sell case.
2. Always cite the raw ATR14 number so downstream readers can sanity-check stop distances.
3. If average volume looks thin, flag illiquidity/slippage risk plainly (this system \
sizes a ~$650 account, where thin volume is disproportionately damaging).
"""


class RationaleOutput(BaseModel):
    rationale: str = Field(max_length=280)


def build_verdict(ticker: str, asset_class: AssetClass, bars: list[NormalizedBar], llm=None) -> AgentVerdict:
    if not bars:
        raise ValueError(f"no bars provided for {ticker}")

    df = pd.DataFrame([b.model_dump() for b in bars]).sort_values("ts_utc")
    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]
    data_quality_flag = bars[-1].data_quality_flag

    sub = compute_volatility_volume(high, low, close, volume)

    confidence = sub.confidence
    if data_quality_flag == DataQualityFlag.STALE:
        confidence = min(confidence, 0.3)

    avg_volume_20d = float(volume.tail(20).mean())
    thin_volume = avg_volume_20d < 100_000  # rough illiquidity heuristic for a small account

    user_prompt = (
        f"Ticker: {ticker} ({asset_class.value})\n"
        f"vol_expansion_score={sub.vol_expansion_score:.3f}, rvol_score={sub.rvol_score:.3f} "
        f"(RVOL={sub.rvol_value:.2f}x), distance_score={sub.distance_score:.3f}\n"
        f"ATR14={sub.atr14:.4f}, vol_conf_multiplier={sub.vol_conf_multiplier:.3f}\n"
        f"signal_score={sub.signal_score:.3f}, confidence={confidence:.3f}\n"
        f"20-day avg volume={avg_volume_20d:,.0f} ({'THIN -- flag illiquidity' if thin_volume else 'adequate'})\n"
        "Write the rationale."
    )

    result = call_structured(SYSTEM_PROMPT, user_prompt, RationaleOutput, llm=llm)

    return AgentVerdict(
        agent_name="VolatilityVolumeAgent",
        asset_class=asset_class,
        ticker=ticker,
        as_of_timestamp=datetime.now(timezone.utc),
        signal_score=sub.signal_score,
        confidence=confidence,
        suggested_holding_period=HoldingPeriod(min_days=3, max_days=15, unit="trading_days"),
        stop_loss=StopLoss(method="atr_multiple", value=2.0, price_level=None),
        profit_target=ProfitTarget(method="atr_multiple", value=2.0),
        rationale=result.rationale,
        sub_scores={
            "vol_expansion_score": sub.vol_expansion_score,
            "rvol_score": sub.rvol_score,
            "distance_score": sub.distance_score,
            "vol_conf_multiplier": sub.vol_conf_multiplier,
            "atr14": sub.atr14,
            "rvol_value": sub.rvol_value,
        },
        regime_gate_applied=None,
        data_quality_flag=data_quality_flag,
    )
