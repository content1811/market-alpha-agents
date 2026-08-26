"""SeasonalityAgent per docs/plan/section_agents.md section 3.

Score/confidence come entirely from signals/ta/seasonality.py's hard-capped
formulas (|signal_score|<=0.3, confidence<=0.5 by construction). The LLM
writes only the rationale.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from pydantic import BaseModel, Field

from agents.llm_client import call_structured
from agents.schemas import AgentVerdict, HoldingPeriod, ProfitTarget, StopLoss
from data.schema import AssetClass, DataQualityFlag, NormalizedBar
from signals.ta.seasonality import compute_seasonality

SYSTEM_PROMPT = """You are a statistically rigorous quant researcher who is \
deliberately skeptical of pattern-matching and actively looks for reasons to \
distrust the pattern (small n, contested EMH literature, arbitraged-away effects). \
You are the rationale-writer for SeasonalityAgent in a local trading-research system.

You will be given already-computed sub-scores, sample sizes, and phase labels. Write \
ONLY the rationale field -- you do not set the score or confidence.

Rules for the rationale (<=280 chars):
1. State sample size (n) inline (e.g. "n=13 Septembers, no formal significance test -- \
low-confidence pattern").
2. Never phrase seasonality as "X historically happens" without noting participants \
have likely already priced in well-known calendar effects.
3. This agent is a thin contrarian-caution tilt, never a standalone trigger -- say so.
"""


class RationaleOutput(BaseModel):
    rationale: str = Field(max_length=280)


BTC_SYMBOLS = {"BTC/USDT", "BTC/USD", "BTC-USD", "BTC"}


def build_verdict(ticker: str, asset_class: AssetClass, bars: list[NormalizedBar], llm=None) -> AgentVerdict:
    if not bars:
        raise ValueError(f"no bars provided for {ticker}")

    df = pd.DataFrame([b.model_dump() for b in bars]).sort_values("ts_utc")
    dates = pd.to_datetime(df["ts_utc"]).dt.tz_localize(None)
    daily_returns = df["close"].pct_change().dropna()
    dates_aligned = dates.iloc[1:].reset_index(drop=True)
    data_quality_flag = bars[-1].data_quality_flag
    as_of = dates.iloc[-1].date()

    surprise_history = None
    days_since_earnings = None
    if asset_class == AssetClass.US_EQUITY:
        try:
            import yfinance as yf

            earnings = yf.Ticker(ticker).get_earnings_dates(limit=12)
            if earnings is not None and not earnings.empty and earnings["Surprise(%)"].notna().any():
                surprise_history = earnings["Surprise(%)"].dropna()
                last_earnings_date = earnings.dropna(subset=["Reported EPS"]).index.max()
                if pd.notna(last_earnings_date):
                    days_since_earnings = (pd.Timestamp(as_of, tz=last_earnings_date.tz) - last_earnings_date).days
        except Exception:
            pass  # earnings calendar is a nice-to-have, not fatal if unavailable

    is_crypto = asset_class == AssetClass.CRYPTO
    is_btc = ticker.upper() in BTC_SYMBOLS

    sub = compute_seasonality(
        daily_returns.reset_index(drop=True),
        dates_aligned,
        as_of=as_of,
        surprise_pct_history=surprise_history,
        days_since_earnings=days_since_earnings,
        is_crypto=is_crypto,
        is_btc=is_btc,
    )

    confidence = sub.confidence
    if data_quality_flag == DataQualityFlag.STALE:
        confidence = min(confidence, 0.3)

    user_prompt = (
        f"Ticker: {ticker} ({asset_class.value}), as-of date: {as_of}\n"
        f"turn_of_month_score={sub.turn_of_month_score:.3f} (n={sub.turn_of_month_n}), "
        f"day_of_week_score={sub.day_of_week_score:.3f} (n={sub.day_of_week_n})\n"
        f"pead_score={sub.pead_score:.3f}"
        + (f", crypto_monthly_score={sub.crypto_monthly_score:.3f}" if sub.crypto_monthly_score is not None else "")
        + (f", halving_phase={sub.halving_phase} (score={sub.halving_score:.3f})" if sub.halving_phase else "")
        + f"\nvolatility_caution={sub.volatility_caution}\n"
        f"signal_score={sub.signal_score:.3f} (hard-capped at +/-0.3), confidence={confidence:.3f} (hard-capped at 0.5)\n"
        "Write the rationale."
    )

    result = call_structured(SYSTEM_PROMPT, user_prompt, RationaleOutput, llm=llm)

    return AgentVerdict(
        agent_name="SeasonalityAgent",
        asset_class=asset_class,
        ticker=ticker,
        as_of_timestamp=datetime.now(timezone.utc),
        signal_score=sub.signal_score,
        confidence=confidence,
        suggested_holding_period=HoldingPeriod(min_days=3, max_days=4, unit="calendar_days"),
        stop_loss=StopLoss(method="percent", value=5.0, price_level=None),
        profit_target=ProfitTarget(method="percent", value=5.0),
        rationale=result.rationale,
        sub_scores={
            "turn_of_month_score": sub.turn_of_month_score,
            "day_of_week_score": sub.day_of_week_score,
            "pead_score": sub.pead_score,
            **({"crypto_monthly_score": sub.crypto_monthly_score} if sub.crypto_monthly_score is not None else {}),
            **({"halving_score": sub.halving_score} if sub.halving_phase else {}),
        },
        regime_gate_applied=f"volatility_caution={sub.volatility_caution}" if sub.volatility_caution else None,
        data_quality_flag=data_quality_flag,
    )
