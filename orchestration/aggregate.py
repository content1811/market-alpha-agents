"""Deterministic aggregation for PortfolioSupervisorAgent, per
docs/plan/section_agents.md sections 10.1-10.3, implemented verbatim where the
plan gives an exact formula. Two terms in the plan's own pseudocode aren't
spelled out precisely and are resolved here as documented judgment calls (see
inline comments): `weight_norm_avg_confidence` and `data_quality_multiplier`.

This is the single authoritative aggregation implementation -- do not build a
second one. See critique.md #1 for why an earlier draft with a competing,
simplified 3-role aggregator was wrong.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import stdev

import numpy as np

from agents.schemas import AgentVerdict, ComponentBreakdownRow, RiskManagerVerdict
from data.schema import AssetClass, DataQualityFlag

# section_agents.md section 10.1 weighting table. VolatilityVolumeAgent's 0.10
# is its direct weighted vote (separate from vol_conf_multiplier, step 2).
BASE_WEIGHTS: dict[AssetClass, dict[str, float]] = {
    AssetClass.US_EQUITY: {
        "TrendMomentumAgent": 0.28,
        "MeanReversionAgent": 0.18,
        "ShortSqueezeAgent": 0.14,
        "SeasonalityAgent": 0.08,
        "NewsSentimentAgent": 0.22,
        "VolatilityVolumeAgent": 0.10,
    },
    AssetClass.JP_EQUITY: {
        "TrendMomentumAgent": 0.28,
        "MeanReversionAgent": 0.18,
        "ShortSqueezeAgent": 0.08,  # degraded data, per section_agents.md section 4
        "SeasonalityAgent": 0.08,
        "NewsSentimentAgent": 0.18,  # thinner JP feed
        "VolatilityVolumeAgent": 0.10,
    },
    AssetClass.CRYPTO: {
        "TrendMomentumAgent": 0.22,
        "MeanReversionAgent": 0.15,
        "SeasonalityAgent": 0.05,
        "NewsSentimentAgent": 0.15,
        "CryptoOnChainAgent": 0.20,
        "CryptoDerivativesAgent": 0.23,
        "VolatilityVolumeAgent": 0.10,
    },
}

DISPERSION_CONFIDENCE_THRESHOLD = 0.3  # only agents above this confidence count toward dispersion
DISPERSION_PENALTY_DIVISOR = 0.7
DISPERSION_PENALTY_CAP = 0.6
SQUEEZE_ELEVATED_THRESHOLD = 0.6
STOP_WIDEN_FRACTION = 0.35  # midpoint of the plan's "+25-50%" range


@dataclass
class AggregationResult:
    blended_score: float
    overall_confidence: float
    disagreement_penalty: float
    component_breakdown: list[ComponentBreakdownRow]
    squeeze_risk_elevated: bool
    volatility_caution: bool
    stop_widen_multiplier: float
    final_call: str
    risk_manager_override: str


def _dispersion_penalty(scores: list[float]) -> float:
    if len(scores) < 2:
        return 0.0
    dispersion = stdev(scores)
    return float(np.clip(dispersion / DISPERSION_PENALTY_DIVISOR, 0.0, DISPERSION_PENALTY_CAP))


def _data_quality_multiplier(verdicts: list[AgentVerdict]) -> float:
    """Not spelled out precisely in the plan's pseudocode. Individual agents
    already cap their OWN confidence when their own data is stale/unavailable
    (the canonical section_data_pipeline.md section 2.4 rule, applied per-agent
    throughout this codebase), so this term is a modest EXTRA dampener only
    for systemic degradation across multiple agents at once (e.g. a ticker-
    wide outage), not a duplicate of the per-agent penalty already baked into
    each verdict's `confidence`."""
    if not verdicts:
        return 1.0
    degraded_fraction = sum(1 for v in verdicts if v.data_quality_flag != DataQualityFlag.OK) / len(verdicts)
    return float(1.0 - 0.5 * degraded_fraction)


def decision_from_blended_score(
    blended_score: float,
    overall_confidence: float,
    buy_sell_threshold: float = 0.35,
    watch_threshold: float = 0.20,
    min_confidence: float = 0.50,
) -> str:
    """section_agents.md section 10.3 decision bands, verbatim. Thresholds are
    parameters, not hardcoded, per the plan's own note that they should be
    tunable config."""
    if overall_confidence < min_confidence:
        return "HOLD"
    if blended_score >= buy_sell_threshold:
        return "BUY"
    if blended_score <= -buy_sell_threshold:
        return "SELL"
    if abs(blended_score) >= watch_threshold:
        return "WATCH"
    return "HOLD"


def aggregate(
    verdicts: list[AgentVerdict],
    risk_verdict: RiskManagerVerdict,
    asset_class: AssetClass,
    regime_multiplier: float = 1.0,
    buy_sell_threshold: float = 0.35,
    watch_threshold: float = 0.20,
    min_confidence: float = 0.50,
) -> AggregationResult:
    weights = BASE_WEIGHTS[asset_class]
    active = [v for v in verdicts if v.agent_name in weights]
    if not active:
        raise ValueError(f"no applicable verdicts for asset class {asset_class.value}")

    vol_agent = next((v for v in active if v.agent_name == "VolatilityVolumeAgent"), None)
    vol_conf_multiplier = vol_agent.sub_scores.get("vol_conf_multiplier", 1.0) if vol_agent else 1.0

    # Step 1 -- confidence-weighted directional blend
    weighted_sum = sum(weights[v.agent_name] * v.signal_score * v.confidence for v in active)
    weight_norm = sum(weights[v.agent_name] * v.confidence for v in active)
    blended_score = weighted_sum / weight_norm if weight_norm else 0.0

    # Step 2 -- volatility/volume confirmation gate
    blended_score = float(np.clip(blended_score * vol_conf_multiplier, -1.0, 1.0))

    # Step 3 -- dispersion/disagreement penalty
    scores_for_dispersion = [v.signal_score for v in active if v.confidence > DISPERSION_CONFIDENCE_THRESHOLD]
    disagreement_penalty = _dispersion_penalty(scores_for_dispersion)
    total_base_weight = sum(weights[v.agent_name] for v in active)
    # weight_norm_avg_confidence: weight_norm (Step 1's confidence-weighted
    # sum) re-normalized by total active base weight -- i.e. the base-weight-
    # weighted average confidence across active agents. Not spelled out
    # precisely in the plan's pseudocode; this is the documented interpretation.
    weight_norm_avg_confidence = weight_norm / total_base_weight if total_base_weight else 0.0
    data_quality_multiplier = _data_quality_multiplier(active)
    overall_confidence = float(
        np.clip(weight_norm_avg_confidence * (1 - disagreement_penalty) * data_quality_multiplier, 0.0, 1.0)
    )

    # Step 4 -- special-case flags (additive, not blended)
    squeeze_agent = next((v for v in active if v.agent_name == "ShortSqueezeAgent"), None)
    squeeze_risk_elevated = bool(squeeze_agent and squeeze_agent.signal_score > SQUEEZE_ELEVATED_THRESHOLD)

    volatility_caution = any(
        (v.regime_gate_applied and "volatility_caution=True" in v.regime_gate_applied) for v in active
    )
    stop_widen_multiplier = 1.0 + STOP_WIDEN_FRACTION if volatility_caution else 1.0

    component_breakdown = [
        ComponentBreakdownRow(
            agent=v.agent_name,
            score=v.signal_score,
            confidence=v.confidence,
            weight=weights[v.agent_name],
            contribution=(weights[v.agent_name] * v.signal_score * v.confidence / weight_norm) if weight_norm else 0.0,
        )
        for v in active
    ]

    # Step 5 -- RiskManagerAgent veto (hard override)
    if risk_verdict.risk_signal == "veto":
        final_call = "HOLD"
        risk_manager_override = "veto"
    else:
        final_call = decision_from_blended_score(blended_score, overall_confidence, buy_sell_threshold, watch_threshold, min_confidence)
        risk_manager_override = risk_verdict.risk_signal if risk_verdict.risk_signal == "reduce_size" else "none"

    return AggregationResult(
        blended_score=blended_score,
        overall_confidence=overall_confidence,
        disagreement_penalty=disagreement_penalty,
        component_breakdown=component_breakdown,
        squeeze_risk_elevated=squeeze_risk_elevated,
        volatility_caution=volatility_caution,
        stop_widen_multiplier=stop_widen_multiplier,
        final_call=final_call,
        risk_manager_override=risk_manager_override,
    )
