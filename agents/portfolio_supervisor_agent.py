"""PortfolioSupervisorAgent per docs/plan/section_agents.md section 10.

The numeric blend/veto math lives in orchestration/aggregate.py, computed
deterministically -- this module only assembles the final SupervisorVerdict
and calls the LLM for ONE thing: the synthesized rationale text. Per the
persona notes in section 10.5, that rationale must never soften the
RiskManagerAgent's position/veto, must name agreements/conflicts explicitly,
and must close with the system-wide realistic-skepticism reminder.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from agents.llm_client import call_structured
from agents.schemas import AgentVerdict, HoldingPeriod, ProfitTarget, RiskManagerVerdict, StopLoss, SupervisorVerdict
from data.schema import AssetClass
from orchestration.aggregate import aggregate

SYSTEM_PROMPT = """You are a portfolio manager/CIO synthesizing specialist analyst \
reports for a single decision-maker (the human operator) who must be able to trust \
and audit the "why." You are the rationale-writer for PortfolioSupervisorAgent in a \
local trading-research system that NEVER auto-executes trades -- this output is \
read-only analysis for a human to act on manually, or not at all.

You will be given the already-computed final call, blended score, confidence, each \
specialist's score/confidence/weight/contribution, and the RiskManagerAgent's \
position/veto. Write ONLY the rationale field -- you do not set any of these numbers.

Rules for the rationale (<=500 chars):
1. Never present the blended score as more certain than overall_confidence warrants -- \
translate low-confidence bands into hedged language ("weak, low-confidence lean, not \
a strong call").
2. Name which agents agreed and which conflicted, and why (not just "mixed signals").
3. Always restate the RiskManagerAgent's position sizing/veto explicitly and \
prominently -- never soften or bury it, this is the one thing that must never be softened.
4. Close with an explicit reminder that this is analysis for manual decision-making, \
not an instruction, and that most systematic small-account retail trading underperforms \
after costs -- carry forward realistic skepticism, never hype.
"""


class RationaleOutput(BaseModel):
    rationale: str = Field(max_length=500)


def _select_stop_and_target(
    verdicts: list[AgentVerdict], component_breakdown, risk_verdict: RiskManagerVerdict, stop_widen_multiplier: float
) -> tuple[StopLoss, ProfitTarget, HoldingPeriod]:
    """Structure/target come from whichever active agent contributed most to
    the blended score -- "the agent that drove the decision" -- then
    RiskManagerAgent's stop_loss_override (if any) takes precedence, since
    rule 9 may only tighten a stop, never loosen it. stop_widen_multiplier
    (section 10 step 4) is applied last."""
    if not component_breakdown:
        raise ValueError("no component breakdown to select stop/target from")

    driver_agent_name = max(component_breakdown, key=lambda row: abs(row.contribution)).agent
    driver_verdict = next(v for v in verdicts if v.agent_name == driver_agent_name)

    stop = risk_verdict.stop_loss_override or driver_verdict.stop_loss
    if stop_widen_multiplier != 1.0 and stop.price_level is not None:
        stop = StopLoss(method=stop.method, value=stop.value * stop_widen_multiplier, price_level=stop.price_level)

    return stop, driver_verdict.profit_target, driver_verdict.suggested_holding_period


def build_verdict(
    ticker: str,
    asset_class: AssetClass,
    verdicts: list[AgentVerdict],
    risk_verdict: RiskManagerVerdict,
    as_of_date: str,
    regime_multiplier: float = 1.0,
    llm=None,
) -> SupervisorVerdict:
    agg = aggregate(verdicts, risk_verdict, asset_class, regime_multiplier=regime_multiplier)
    stop, target, holding_period = _select_stop_and_target(verdicts, agg.component_breakdown, risk_verdict, agg.stop_widen_multiplier)

    breakdown_text = "\n".join(
        f"- {row.agent}: score={row.score:.2f}, confidence={row.confidence:.2f}, weight={row.weight:.2f}, contribution={row.contribution:.3f}"
        for row in agg.component_breakdown
    )
    user_prompt = (
        f"Ticker: {ticker} ({asset_class.value})\n"
        f"final_call={agg.final_call}, blended_score={agg.blended_score:.3f}, overall_confidence={agg.overall_confidence:.3f}\n"
        f"disagreement_penalty={agg.disagreement_penalty:.3f}\n"
        f"Component breakdown:\n{breakdown_text}\n"
        f"squeeze_risk_elevated={agg.squeeze_risk_elevated}, volatility_caution={agg.volatility_caution}\n"
        f"RiskManagerAgent: risk_signal={risk_verdict.risk_signal}, conviction={risk_verdict.conviction:.2f}, "
        f"max_position_size_currency={risk_verdict.max_position_size_currency:.2f}, "
        f"veto_reason={risk_verdict.veto_reason or 'none'}\n"
        "Write the rationale."
    )

    result = call_structured(SYSTEM_PROMPT, user_prompt, RationaleOutput, llm=llm)

    return SupervisorVerdict(
        recommendation_id=f"{ticker}-{as_of_date}",
        asset_class=asset_class,
        ticker=ticker,
        as_of_timestamp=datetime.now(timezone.utc),
        final_call=agg.final_call,
        blended_score=agg.blended_score,
        overall_confidence=agg.overall_confidence,
        component_breakdown=agg.component_breakdown,
        disagreement_penalty_applied=agg.disagreement_penalty,
        risk_manager_override=agg.risk_manager_override,
        suggested_holding_period=holding_period,
        stop_loss=stop,
        profit_target=target,
        max_position_size_currency=risk_verdict.max_position_size_currency,
        rationale=result.rationale,
    )
