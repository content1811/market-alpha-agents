"""CryptoDerivativesAgent per docs/plan/section_agents.md section 7.

Score/confidence come entirely from signals/crypto_composite.py. The LLM
writes only the rationale. Skew (Deribit options chain) is not wired to a
live source yet -- see signals/crypto_composite.py's module docstring -- so
skew_z is always None here today; the composite math already handles that by
excluding it from the weighted average rather than guessing.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from agents.llm_client import call_structured
from agents.schemas import AgentVerdict, HoldingPeriod, ProfitTarget, StopLoss
from data.schema import AssetClass
from signals.crypto_composite import compute_crypto_derivatives

SYSTEM_PROMPT = """You are a derivatives/positioning specialist, contrarian by \
default (fades crowding), highly mechanical about leverage risk. You are the \
rationale-writer for CryptoDerivativesAgent in a local trading-research system.

You will be given already-computed sub-scores. Write ONLY the rationale field -- \
you do not set the score or confidence.

Rules for the rationale (<=280 chars):
1. Always report both the funding *level* and note this is contrarian-scored (high \
funding -> bearish score) since the crowd can already be unwinding by the time a \
level looks extreme.
2. If squeeze_risk_flag is true, flag it as a risk-sizing note for RiskManagerAgent, \
NOT a trade trigger -- never suggest trying to "trade the cascade" directly.
3. Never claim certainty about timing.
"""


class RationaleOutput(BaseModel):
    rationale: str = Field(max_length=280)


def build_verdict(
    ticker: str,
    funding_rate_history: list[float],
    current_price: float,
    prior_price: float,
    current_oi: float,
    prior_oi: float,
    periods_per_day: int = 3,
    skew_z: float | None = None,
    llm=None,
) -> AgentVerdict:
    if not funding_rate_history:
        raise ValueError(f"no funding rate history provided for {ticker}")

    sub = compute_crypto_derivatives(
        funding_rate_history=funding_rate_history,
        current_price=current_price,
        prior_price=prior_price,
        current_oi=current_oi,
        prior_oi=prior_oi,
        skew_z=skew_z,
        periods_per_day=periods_per_day,
    )

    current_annualized_pct = funding_rate_history[-1] * periods_per_day * 365 * 100

    user_prompt = (
        f"Ticker: {ticker} (crypto perpetual futures)\n"
        f"Current funding rate={funding_rate_history[-1]:.6f} per period "
        f"(~{current_annualized_pct:.1f}% annualized)\n"
        f"funding_score={sub.funding_score:.3f} (contrarian sign), oi_score={sub.oi_score:.3f}, "
        f"skew_score={sub.skew_score:.3f} ({'included' if skew_z is not None else 'unavailable, excluded'})\n"
        f"squeeze_risk_flag={sub.squeeze_risk_flag}\n"
        f"signal_score={sub.signal_score:.3f}, confidence={sub.confidence:.3f}\n"
        f"Price {prior_price:.2f} -> {current_price:.2f}, OI {prior_oi:.0f} -> {current_oi:.0f}\n"
        "Write the rationale."
    )

    result = call_structured(SYSTEM_PROMPT, user_prompt, RationaleOutput, llm=llm)

    return AgentVerdict(
        agent_name="CryptoDerivativesAgent",
        asset_class=AssetClass.CRYPTO,
        ticker=ticker,
        as_of_timestamp=datetime.now(timezone.utc),
        signal_score=sub.signal_score,
        confidence=sub.confidence,
        suggested_holding_period=HoldingPeriod(min_days=2, max_days=10, unit="calendar_days"),
        stop_loss=StopLoss(method="percent", value=5.0 if not sub.squeeze_risk_flag else 3.0, price_level=None),
        profit_target=ProfitTarget(method="percent", value=8.0),
        rationale=result.rationale,
        sub_scores={
            "funding_score": sub.funding_score,
            "oi_score": sub.oi_score,
            "skew_score": sub.skew_score,
            "liquidation_caution": float(sub.squeeze_risk_flag),
        },
        regime_gate_applied=f"squeeze_risk_flag={sub.squeeze_risk_flag}" if sub.squeeze_risk_flag else None,
    )
