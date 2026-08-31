"""ShortSqueezeAgent per docs/plan/section_agents.md section 4.

Runs in an explicitly degraded mode today: FINRA short interest and a
borrow-fee/utilization source aren't connected yet (Phase 1 remaining work),
so only options_score is real -- computed live from yfinance's free, keyless
option_chain(). signals/squeeze.py's compute_squeeze() handles this by
re-normalizing the weighted average over whatever's actually available
rather than silently zeroing the missing inputs. Crypto has no equivalent
(the plan routes squeeze-like positioning risk to CryptoDerivativesAgent's
funding/OI instead), so this agent is US/JP equity only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from agents.llm_client import call_structured
from agents.schemas import AgentVerdict, HoldingPeriod, ProfitTarget, StopLoss
from data.schema import AssetClass
from signals.squeeze import OptionRow, compute_squeeze

SYSTEM_PROMPT = """You are a risk-aware special-situations trader who treats squeezes \
as high-variance lottery-like setups worth flagging but not sizing heavily -- \
explicitly NOT a hype-driven "meme stock" persona. You are the rationale-writer for \
ShortSqueezeAgent in a local trading-research system.

You will be given already-computed sub-scores and a list of degraded/unavailable \
inputs. Write ONLY the rationale field -- you do not set the score or confidence.

Rules for the rationale (<=280 chars):
1. If any inputs are degraded/unavailable, say so plainly (e.g. "short-interest data \
unavailable, options-flow-only read, low confidence").
2. Never phrase this as a standalone buy signal -- include something like "combine with \
a directional catalyst before acting."
3. Never imply certainty of a squeeze occurring or its timing, even at signal_score=1.0.
"""


class RationaleOutput(BaseModel):
    rationale: str = Field(max_length=280)


def fetch_option_rows(ticker: str) -> list[OptionRow]:
    import yfinance as yf

    t = yf.Ticker(ticker)
    expirations = t.options
    if not expirations:
        return []
    calls = t.option_chain(expirations[0]).calls
    return [
        OptionRow(
            strike=float(r.strike),
            last_price=float(r.lastPrice),
            bid=float(r.bid),
            ask=float(r.ask),
            volume=float(r.volume) if r.volume == r.volume else 0.0,  # NaN check
            open_interest=float(r.openInterest) if r.openInterest == r.openInterest else 0.0,
        )
        for r in calls.itertuples()
    ]


def build_verdict(
    ticker: str,
    asset_class: AssetClass,
    si_pct_of_float: float | None = None,
    days_to_cover: float | None = None,
    borrow_fee_rate_pct: float | None = None,
    utilization_pct: float | None = None,
    option_rows: list[OptionRow] | None = None,
    rvol: float | None = None,
    llm=None,
) -> AgentVerdict:
    if asset_class == AssetClass.CRYPTO:
        raise ValueError("ShortSqueezeAgent does not apply to crypto -- see CryptoDerivativesAgent instead")

    if option_rows is None:
        option_rows = fetch_option_rows(ticker)

    is_jp = asset_class == AssetClass.JP_EQUITY
    sub = compute_squeeze(
        si_pct_of_float=si_pct_of_float,
        days_to_cover=days_to_cover,
        borrow_fee_rate_pct=borrow_fee_rate_pct,
        utilization_pct=utilization_pct,
        option_rows=option_rows,
        rvol=rvol,
        is_jp=is_jp,
    )

    degraded_note = "; ".join(sub.degraded_fields) if sub.degraded_fields else "none"
    user_prompt = (
        f"Ticker: {ticker} ({asset_class.value})\n"
        f"si_score={sub.si_score:.3f}, dtc_score={sub.dtc_score:.3f}, fee_score={sub.fee_score:.3f}, "
        f"util_score={sub.util_score:.3f}, options_score={sub.options_score:.3f}\n"
        f"Degraded/unavailable inputs: {degraded_note}\n"
        f"signal_score={sub.signal_score:.3f} (never negative, one-sided), confidence={sub.confidence:.3f}\n"
        "Write the rationale."
    )

    result = call_structured(SYSTEM_PROMPT, user_prompt, RationaleOutput, llm=llm)

    return AgentVerdict(
        agent_name="ShortSqueezeAgent",
        asset_class=asset_class,
        ticker=ticker,
        as_of_timestamp=datetime.now(timezone.utc),
        signal_score=sub.signal_score,
        confidence=sub.confidence,
        suggested_holding_period=HoldingPeriod(min_days=1, max_days=3, unit="trading_days"),
        stop_loss=StopLoss(method="percent", value=10.0, price_level=None),
        profit_target=ProfitTarget(method="percent", value=30.0),
        rationale=result.rationale,
        sub_scores={
            "si_score": sub.si_score,
            "dtc_score": sub.dtc_score,
            "fee_score": sub.fee_score,
            "util_score": sub.util_score,
            "options_score": sub.options_score,
        },
        regime_gate_applied=f"degraded: {degraded_note}" if sub.degraded_fields else None,
    )
