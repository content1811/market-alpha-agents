"""Agent-level tests for PortfolioSupervisorAgent."""
from __future__ import annotations

from datetime import datetime, timezone

from agents.portfolio_supervisor_agent import build_verdict
from agents.schemas import AgentVerdict, HoldingPeriod, ProfitTarget, RiskManagerVerdict, StopLoss
from data.schema import AssetClass
from tests.test_agents.test_mean_reversion_agent import FakeLLM

APPROVE_RISK = RiskManagerVerdict(
    risk_signal="approve", conviction=0.0, max_position_size_pct_equity=10, max_position_size_currency=10000, structural_feasibility="ok"
)


def _verdict(name: str, score: float, confidence: float) -> AgentVerdict:
    return AgentVerdict(
        agent_name=name,
        asset_class=AssetClass.US_EQUITY,
        ticker="AAPL",
        as_of_timestamp=datetime.now(timezone.utc),
        signal_score=score,
        confidence=confidence,
        suggested_holding_period=HoldingPeriod(min_days=1, max_days=5, unit="trading_days"),
        stop_loss=StopLoss(method="structure", value=100.0, price_level=100.0),
        profit_target=ProfitTarget(method="structure", value=120.0, price_level=120.0),
        rationale="x",
        sub_scores={"vol_conf_multiplier": 1.0} if name == "VolatilityVolumeAgent" else {},
    )


def test_portfolio_supervisor_agent_end_to_end_with_fake_llm():
    verdicts = [
        _verdict("TrendMomentumAgent", 0.6, 0.8),
        _verdict("MeanReversionAgent", -0.2, 0.5),
        _verdict("VolatilityVolumeAgent", 0.1, 0.9),
    ]
    llm = FakeLLM(responses=['{"rationale": "TrendMomentum bullish, MeanReversion mildly bearish, disagreement drags confidence. Risk approves. Manual analysis only."}'])

    verdict = build_verdict("AAPL", AssetClass.US_EQUITY, verdicts, APPROVE_RISK, as_of_date="2026-08-26", llm=llm)

    assert verdict.recommendation_id == "AAPL-2026-08-26"
    assert verdict.human_action_required is True
    assert len(verdict.component_breakdown) == 3
    assert verdict.risk_manager_override == "none"


def test_portfolio_supervisor_agent_veto_propagates():
    veto_risk = RiskManagerVerdict(
        risk_signal="veto", conviction=0.9, max_position_size_pct_equity=0, max_position_size_currency=0,
        structural_feasibility="ok", veto_reason="drawdown breaker",
    )
    verdicts = [_verdict("TrendMomentumAgent", 0.9, 0.9), _verdict("VolatilityVolumeAgent", 0.5, 0.9)]
    llm = FakeLLM(responses=['{"rationale": "Risk manager vetoed due to drawdown breaker; HOLD despite bullish specialists."}'])

    verdict = build_verdict("AAPL", AssetClass.US_EQUITY, verdicts, veto_risk, as_of_date="2026-08-26", llm=llm)

    assert verdict.final_call == "HOLD"
    assert verdict.risk_manager_override == "veto"
    assert verdict.max_position_size_currency == 0.0
