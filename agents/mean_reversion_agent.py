"""MeanReversionAgent per docs/plan/section_agents.md section 1.

Design principle enforced here (section_agents.md section 0 + section 1's
persona note #4: "refuse to raise its own score above what the deterministic
sub-score formulas produce"): signal_score, confidence, and sub_scores are
computed entirely in code by signals/ta/mean_reversion.py. The LLM is called
ONLY to write the rationale string -- it never sets or influences the score.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from pydantic import BaseModel, Field

from agents.llm_client import call_structured
from agents.schemas import AgentVerdict, HoldingPeriod, ProfitTarget, StopLoss
from data.schema import AssetClass, DataQualityFlag, NormalizedBar
from signals.ta.mean_reversion import bollinger_bands, compute_mean_reversion
from signals.ta.trend_momentum import atr

SYSTEM_PROMPT = """You are a disciplined short-term quant/prop trader who distrusts \
narrative and only trusts statistics that have passed a regime check. You are the \
rationale-writer for MeanReversionAgent in a local trading-research system.

You will be given already-computed sub-scores, an ADX regime reading, and price \
levels. Write ONLY the rationale field -- you do not set the score or confidence, \
they are fixed by deterministic code and are not yours to change.

Rules for the rationale (<=280 chars):
1. State the ADX reading and whether the mean-reversion gate is active or suppressed \
BEFORE any other claim.
2. If trend_confidence is high (gate suppressed), say so plainly and explain the \
score is being suppressed, not that a fade is being recommended.
3. Never use language implying certainty ("will bounce"). Use probabilistic framing \
("elevated probability of reversion toward X, not a guarantee").
4. Cite the specific numbers that drove the score (e.g. the %B, RSI-2, z-score, or \
band level actually computed) -- never vague language like "oversold conditions."
"""


class RationaleOutput(BaseModel):
    rationale: str = Field(max_length=280)


def _regime_gate_description(adx_value: float, trend_confidence: float) -> str:
    if trend_confidence >= 1.0:
        return f"ADX={adx_value:.1f}, trend regime, mean-reversion fully suppressed"
    if trend_confidence <= 0.0:
        return f"ADX={adx_value:.1f}, no trend, mean-reversion gate fully open"
    return f"ADX={adx_value:.1f}, ambiguous regime, mean-reversion scaled by {1 - trend_confidence:.2f}"


def build_verdict(ticker: str, asset_class: AssetClass, bars: list[NormalizedBar], llm=None) -> AgentVerdict:
    if not bars:
        raise ValueError(f"no bars provided for {ticker}")

    df = pd.DataFrame([b.model_dump() for b in bars]).sort_values("ts_utc")
    high, low, close = df["high"], df["low"], df["close"]
    data_quality_flag = bars[-1].data_quality_flag

    sub = compute_mean_reversion(high, low, close)

    # data_quality_flag propagation rule, canonical definition in
    # docs/plan/section_data_pipeline.md section 2.4: stale caps confidence <=0.3.
    confidence = sub.confidence
    if data_quality_flag == DataQualityFlag.STALE:
        confidence = min(confidence, 0.3)

    lower_band, mid_band, upper_band = bollinger_bands(close)
    atr14 = atr(high, low, close).iloc[-1]
    last_price = close.iloc[-1]

    is_long_fade = sub.bb_score > 0  # bb_score>0 means price below lower band -> long fade
    if is_long_fade:
        structure_stop = float(lower_band.iloc[-1] - 0.5 * atr14)
    else:
        structure_stop = float(upper_band.iloc[-1] + 0.5 * atr14)
    atr_floor = float(last_price - 1.5 * atr14) if is_long_fade else float(last_price + 1.5 * atr14)
    # sanity floor: never let the structure stop be tighter than the ATR floor
    final_stop = min(structure_stop, atr_floor) if is_long_fade else max(structure_stop, atr_floor)

    regime_note = _regime_gate_description(sub.adx_value, sub.trend_confidence)

    user_prompt = (
        f"Ticker: {ticker} ({asset_class.value})\n"
        f"Sub-scores: bb_score={sub.bb_score:.3f}, rsi2_score={sub.rsi2_score:.3f}, "
        f"z_score={sub.z_score:.3f}\n"
        f"Regime: {regime_note}\n"
        f"signal_score={sub.signal_score:.3f}, confidence={confidence:.3f}\n"
        f"Last price={last_price:.2f}, lower_band={lower_band.iloc[-1]:.2f}, "
        f"mid_band={mid_band.iloc[-1]:.2f}, upper_band={upper_band.iloc[-1]:.2f}, "
        f"ATR14={atr14:.2f}\n"
        f"Proposed stop_loss={final_stop:.2f}, profit_target={mid_band.iloc[-1]:.2f}\n"
        "Write the rationale."
    )

    result = call_structured(SYSTEM_PROMPT, user_prompt, RationaleOutput, llm=llm)

    return AgentVerdict(
        agent_name="MeanReversionAgent",
        asset_class=asset_class,
        ticker=ticker,
        as_of_timestamp=datetime.now(timezone.utc),
        signal_score=sub.signal_score,
        confidence=confidence,
        suggested_holding_period=HoldingPeriod(min_days=1, max_days=5, unit="trading_days"),
        stop_loss=StopLoss(method="structure", value=final_stop, price_level=final_stop),
        profit_target=ProfitTarget(method="structure", value=mid_band.iloc[-1], price_level=float(mid_band.iloc[-1])),
        rationale=result.rationale,
        sub_scores={
            "bb_score": sub.bb_score,
            "rsi2_score": sub.rsi2_score,
            "z_score": sub.z_score,
            "trend_confidence": sub.trend_confidence,
            "adx_value": sub.adx_value,
        },
        regime_gate_applied=regime_note,
        data_quality_flag=data_quality_flag,
    )
