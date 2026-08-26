"""Unit tests for orchestration/aggregate.py, per section_agents.md sections
10.1-10.3 -- hand-computed fixtures for the deterministic aggregation.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agents.schemas import AgentVerdict, HoldingPeriod, ProfitTarget, RiskManagerVerdict, StopLoss
from data.schema import AssetClass, DataQualityFlag
from orchestration.aggregate import aggregate, decision_from_blended_score


def _verdict(name: str, score: float, confidence: float, sub_scores=None, regime_gate_applied=None, dq_flag=DataQualityFlag.OK) -> AgentVerdict:
    return AgentVerdict(
        agent_name=name,
        asset_class=AssetClass.US_EQUITY,
        ticker="X",
        as_of_timestamp=datetime.now(timezone.utc),
        signal_score=score,
        confidence=confidence,
        suggested_holding_period=HoldingPeriod(min_days=1, max_days=5, unit="trading_days"),
        stop_loss=StopLoss(method="percent", value=5.0),
        profit_target=ProfitTarget(method="percent", value=5.0),
        rationale="x",
        sub_scores=sub_scores or {},
        regime_gate_applied=regime_gate_applied,
        data_quality_flag=dq_flag,
    )


APPROVE_RISK = RiskManagerVerdict(
    risk_signal="approve", conviction=0.0, max_position_size_pct_equity=10, max_position_size_currency=10000, structural_feasibility="ok"
)
VETO_RISK = RiskManagerVerdict(
    risk_signal="veto", conviction=0.9, max_position_size_pct_equity=0, max_position_size_currency=0,
    structural_feasibility="ok", veto_reason="drawdown breaker",
)


def test_aggregate_hand_computed():
    verdicts = [
        _verdict("TrendMomentumAgent", 0.6, 0.8),
        _verdict("MeanReversionAgent", -0.2, 0.5),
        _verdict("VolatilityVolumeAgent", 0.1, 0.9, {"vol_conf_multiplier": 1.0}),
    ]
    result = aggregate(verdicts, APPROVE_RISK, AssetClass.US_EQUITY)

    # weighted_sum = 0.28*0.6*0.8 + 0.18*-0.2*0.5 + 0.10*0.1*0.9 = 0.1254
    # weight_norm = 0.28*0.8 + 0.18*0.5 + 0.10*0.9 = 0.404
    # blended_score = 0.1254/0.404 = 0.310396
    assert result.blended_score == pytest.approx(0.310396, abs=1e-4)
    # stdev([0.6,-0.2,0.1]) = 0.404133; disagreement_penalty = clip(0.404133/0.7,0,0.6) = 0.577350
    assert result.disagreement_penalty == pytest.approx(0.577350, abs=1e-4)
    # weight_norm_avg_confidence = 0.404/0.56 = 0.721429; overall_confidence = 0.721429*(1-0.577350) = 0.304912
    assert result.overall_confidence == pytest.approx(0.304912, abs=1e-4)
    assert result.final_call == "HOLD"  # overall_confidence < 0.50 min_confidence


def test_decision_bands_hand_computed():
    assert decision_from_blended_score(0.40, 0.60) == "BUY"
    assert decision_from_blended_score(-0.40, 0.60) == "SELL"
    assert decision_from_blended_score(0.25, 0.60) == "WATCH"
    assert decision_from_blended_score(0.10, 0.60) == "HOLD"
    assert decision_from_blended_score(0.90, 0.30) == "HOLD"  # confidence gate overrides a strong score


def test_veto_forces_hold_regardless_of_blended_score():
    verdicts = [_verdict("TrendMomentumAgent", 0.9, 0.9), _verdict("VolatilityVolumeAgent", 0.9, 0.9, {"vol_conf_multiplier": 1.0})]
    result = aggregate(verdicts, VETO_RISK, AssetClass.US_EQUITY)
    assert result.final_call == "HOLD"
    assert result.risk_manager_override == "veto"


def test_reduce_size_does_not_force_hold():
    reduce_risk = RiskManagerVerdict(
        risk_signal="reduce_size", conviction=0.4, max_position_size_pct_equity=5, max_position_size_currency=5000,
        structural_feasibility="ok",
    )
    verdicts = [_verdict("TrendMomentumAgent", 0.9, 0.9), _verdict("VolatilityVolumeAgent", 0.5, 0.9, {"vol_conf_multiplier": 1.0})]
    result = aggregate(verdicts, reduce_risk, AssetClass.US_EQUITY)
    assert result.risk_manager_override == "reduce_size"
    assert result.final_call in ("BUY", "WATCH")  # not forced to HOLD


def test_squeeze_risk_elevated_flag():
    verdicts = [
        _verdict("ShortSqueezeAgent", 0.8, 0.6),
        _verdict("VolatilityVolumeAgent", 0.1, 0.9, {"vol_conf_multiplier": 1.0}),
    ]
    result = aggregate(verdicts, APPROVE_RISK, AssetClass.US_EQUITY)
    assert result.squeeze_risk_elevated is True


def test_volatility_caution_widens_stop():
    verdicts = [
        _verdict("SeasonalityAgent", 0.1, 0.4, regime_gate_applied="volatility_caution=True"),
        _verdict("VolatilityVolumeAgent", 0.1, 0.9, {"vol_conf_multiplier": 1.0}),
    ]
    result = aggregate(verdicts, APPROVE_RISK, AssetClass.US_EQUITY)
    assert result.volatility_caution is True
    assert result.stop_widen_multiplier == pytest.approx(1.35)


def test_dispersion_penalty_not_skewed_by_low_confidence_agents():
    # a low-confidence (<=0.3) agent's wildly different score must be excluded
    # from the dispersion calc entirely, per section_agents.md section 10.2 step 3.
    verdicts = [
        _verdict("TrendMomentumAgent", 0.5, 0.8),
        _verdict("MeanReversionAgent", 0.5, 0.8),
        _verdict("NewsSentimentAgent", -0.99, 0.1),  # low confidence, wildly opposite -- excluded
        _verdict("VolatilityVolumeAgent", 0.5, 0.9, {"vol_conf_multiplier": 1.0}),
    ]
    result = aggregate(verdicts, APPROVE_RISK, AssetClass.US_EQUITY)
    assert result.disagreement_penalty == pytest.approx(0.0)  # all counted scores are identical (0.5)


def test_raises_when_no_applicable_agents_for_asset_class():
    with pytest.raises(ValueError):
        aggregate([_verdict("CryptoOnChainAgent", 0.5, 0.5)], APPROVE_RISK, AssetClass.US_EQUITY)
