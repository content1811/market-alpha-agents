"""TrendMomentumAgent per docs/plan/section_agents.md section 2.

Same design principle as MeanReversionAgent: signal_score/confidence/sub_scores
are computed entirely by signals/ta/trend_momentum.py. The LLM writes only the
rationale string.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from pydantic import BaseModel, Field

from agents.llm_client import call_structured
from agents.schemas import AgentVerdict, HoldingPeriod, ProfitTarget, StopLoss
from data.schema import AssetClass, DataQualityFlag, NormalizedBar
from signals.ta.trend_momentum import atr, compute_trend_momentum, donchian_high

PROXY_BY_ASSET_CLASS = {
    AssetClass.US_EQUITY: "SPY",
    AssetClass.JP_EQUITY: "^TOPX",
    AssetClass.CRYPTO: "BTC/USDT",
}

SYSTEM_PROMPT = """You are a systematic trend-follower in the CTA/Turtle tradition -- \
comfortable with a low win rate if the payoff structure is right, allergic to \
prediction, focused on "what is the trend doing right now," not "what will it do." \
You are the rationale-writer for TrendMomentumAgent in a local trading-research system.

You will be given already-computed sub-scores, an ADX regime reading, and price \
levels. Write ONLY the rationale field -- you do not set the score or confidence.

Rules for the rationale (<=280 chars):
1. Must explicitly state the current ADX value and whether the trend gate is open.
2. Never claim to predict trend continuation -- only characterize current strength/direction.
3. Flag "chasing" risk explicitly whenever price is far above the cited breakout level \
with no pullback.
4. Cite the specific MA spread or Donchian level and current ADX value -- never vague \
language like "strong momentum."
"""


class RationaleOutput(BaseModel):
    rationale: str = Field(max_length=280)


def _holding_period_and_stop(sub, atr14: float, last_price: float) -> tuple[HoldingPeriod, StopLoss, str]:
    # "the agent must declare which sub-model dominated the score and set the
    # holding period accordingly" -- section_agents.md section 2, Output specifics.
    ma_swing_weight = abs(sub.ma_score) + abs(sub.macd_score)
    position_weight = abs(sub.xsect_score) + abs(sub.donchian_score)
    if position_weight >= ma_swing_weight:
        dominant = "cross-sectional/Donchian position-trade"
        holding = HoldingPeriod(min_days=15, max_days=90, unit="calendar_days")
        stop_multiple = 2.5
    else:
        dominant = "9/21 EMA swing"
        holding = HoldingPeriod(min_days=3, max_days=10, unit="trading_days")
        stop_multiple = 1.5

    direction = 1 if sub.signal_score >= 0 else -1
    stop_value = float(last_price - direction * stop_multiple * atr14)
    stop = StopLoss(method="atr_multiple", value=stop_multiple, price_level=stop_value)
    return holding, stop, dominant


def build_verdict(
    ticker: str,
    asset_class: AssetClass,
    bars: list[NormalizedBar],
    proxy_bars: list[NormalizedBar],
    llm=None,
) -> AgentVerdict:
    if not bars or not proxy_bars:
        raise ValueError(f"missing bars or proxy_bars for {ticker}")

    df = pd.DataFrame([b.model_dump() for b in bars]).sort_values("ts_utc")
    proxy_df = pd.DataFrame([b.model_dump() for b in proxy_bars]).sort_values("ts_utc")
    high, low, close = df["high"], df["low"], df["close"]
    data_quality_flag = bars[-1].data_quality_flag

    sub = compute_trend_momentum(high, low, close, proxy_df["close"])

    confidence = sub.trend_confidence
    if data_quality_flag == DataQualityFlag.STALE:
        confidence = min(confidence, 0.3)

    atr14 = atr(high, low, close).iloc[-1]
    last_price = close.iloc[-1]
    prior_high = donchian_high(high).iloc[-1]
    holding, stop, dominant = _holding_period_and_stop(sub, atr14, last_price)

    chasing = last_price > prior_high * 1.15
    if chasing:
        confidence = max(0.0, confidence - 0.2)

    gate_note = (
        f"ADX={sub.adx_value:.1f}, trend gate "
        f"{'open' if sub.trend_confidence > 0 else 'closed'} "
        f"(trend_confidence={sub.trend_confidence:.2f}), dominant model: {dominant}"
    )

    proxy_symbol = PROXY_BY_ASSET_CLASS[asset_class]
    user_prompt = (
        f"Ticker: {ticker} ({asset_class.value}), benchmark proxy: {proxy_symbol}\n"
        f"Sub-scores: ma_score={sub.ma_score:.3f}, donchian_score={sub.donchian_score:.3f}, "
        f"xsect_score={sub.xsect_score:.3f}, macd_score={sub.macd_score:.3f}\n"
        f"Regime: {gate_note}\n"
        f"signal_score={sub.signal_score:.3f}, confidence={confidence:.3f}\n"
        f"Last price={last_price:.2f}, prior_donchian_high={prior_high:.2f}, ATR14={atr14:.2f}\n"
        f"Chasing risk (>15% above breakout with no pullback): {chasing}\n"
        f"Proposed stop_loss={stop.price_level:.2f} ({stop.value}x ATR)\n"
        "Write the rationale."
    )

    result = call_structured(SYSTEM_PROMPT, user_prompt, RationaleOutput, llm=llm)

    profit_target = (
        ProfitTarget(method="r_multiple", value=2.5)
        if "position-trade" in dominant
        else ProfitTarget(method="r_multiple", value=2.0)
    )

    return AgentVerdict(
        agent_name="TrendMomentumAgent",
        asset_class=asset_class,
        ticker=ticker,
        as_of_timestamp=datetime.now(timezone.utc),
        signal_score=sub.signal_score,
        confidence=confidence,
        suggested_holding_period=holding,
        stop_loss=stop,
        profit_target=profit_target,
        rationale=result.rationale,
        sub_scores={
            "ma_score": sub.ma_score,
            "donchian_score": sub.donchian_score,
            "xsect_score": sub.xsect_score,
            "macd_score": sub.macd_score,
            "trend_confidence": sub.trend_confidence,
            "adx_value": sub.adx_value,
        },
        regime_gate_applied=gate_note,
        data_quality_flag=data_quality_flag,
    )
