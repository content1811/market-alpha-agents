"""Shared JSON envelope for specialist agents, per docs/plan/section_agents.md
section 0. RiskManagerAgent and MarketRegimeAgent are gates/modifiers, not
directional voters, and define their own schemas below instead of AgentVerdict.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from data.schema import AssetClass, DataQualityFlag

HoldingPeriodUnit = Literal["trading_days", "calendar_days", "hours"]
StopLossMethod = Literal["percent", "atr_multiple", "structure", "vwap_sigma"]
ProfitTargetMethod = Literal["percent", "atr_multiple", "r_multiple", "structure"]


class HoldingPeriod(BaseModel):
    min_days: float
    max_days: float
    unit: HoldingPeriodUnit


class StopLoss(BaseModel):
    method: StopLossMethod
    value: float
    price_level: Optional[float] = None


class ProfitTarget(BaseModel):
    method: ProfitTargetMethod
    value: float
    price_level: Optional[float] = None


class AgentVerdict(BaseModel):
    """Emitted by every directional specialist: MeanReversionAgent,
    TrendMomentumAgent, SeasonalityAgent, ShortSqueezeAgent,
    VolatilityVolumeAgent, CryptoOnChainAgent, CryptoDerivativesAgent,
    NewsSentimentAgent.
    """

    agent_name: str
    asset_class: AssetClass
    ticker: str
    as_of_timestamp: datetime
    signal_score: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_holding_period: HoldingPeriod
    stop_loss: StopLoss
    profit_target: ProfitTarget
    rationale: str = Field(max_length=280)
    sub_scores: dict[str, float] = Field(default_factory=dict)
    regime_gate_applied: Optional[str] = None
    data_quality_flag: DataQualityFlag = DataQualityFlag.OK


RiskSignal = Literal["approve", "reduce_size", "veto"]
StructuralFeasibility = Literal["ok", "infeasible_lot_size", "infeasible_margin_floor"]
JPLimitBandFlag = Literal["none", "approaching_limit", "limit_lock_risk", "stop_outside_band"]


class RiskManagerVerdict(BaseModel):
    """RiskManagerAgent (section_agents.md section 9) -- a gate/modifier, never
    a weighted directional vote. No LLM call: every field here is deterministic,
    per the plan's own rules 1-9, so there is nothing for an LLM to interpret."""

    risk_signal: RiskSignal
    conviction: float = Field(ge=0.0, le=1.0)
    max_position_size_pct_equity: float
    max_position_size_currency: float
    stop_loss_override: Optional[StopLoss] = None
    structural_feasibility: StructuralFeasibility
    jp_limit_band_flag: Optional[JPLimitBandFlag] = Field(
        default=None, description="Rule 9, JP tickers only; null for non-JP asset classes."
    )
    veto_reason: Optional[str] = None


class MarketRegimeVerdict(BaseModel):
    """MarketRegimeAgent (section_agents.md section 11) -- system-wide per
    asset class, not per-ticker. No LLM call, no rationale field, per the
    plan's own output schema (section 11's JSON block has neither)."""

    agent_name: Literal["MarketRegimeAgent"] = "MarketRegimeAgent"
    asset_class: AssetClass
    as_of_timestamp: datetime
    vol_percentile: float = Field(ge=0.0, le=100.0)
    regime_breaker_active: bool
    position_size_ceiling_multiplier: float = Field(ge=0.0, le=1.0)
    data_quality_flag: DataQualityFlag = DataQualityFlag.OK


FinalCall = Literal["BUY", "SELL", "HOLD", "WATCH"]
RiskManagerOverride = Literal["none", "reduce_size", "veto"]


class ComponentBreakdownRow(BaseModel):
    agent: str
    score: float
    confidence: float
    weight: float
    contribution: float


class SupervisorVerdict(BaseModel):
    """PortfolioSupervisorAgent (section_agents.md section 10.5) -- deterministic
    aggregation output, computed by orchestration/aggregate.py, not another LLM
    call. `rationale` is the only LLM-authored field. `human_action_required` is
    always True: this is a terminal artifact, never an input to an execution tool
    that doesn't exist in this system."""

    agent_name: Literal["PortfolioSupervisorAgent"] = "PortfolioSupervisorAgent"
    recommendation_id: str = Field(description="f'{ticker}-{as_of_date}', == LangGraph thread_id")
    asset_class: AssetClass
    ticker: str
    as_of_timestamp: datetime
    final_call: FinalCall
    blended_score: float = Field(ge=-1.0, le=1.0)
    overall_confidence: float = Field(ge=0.0, le=1.0)
    component_breakdown: list[ComponentBreakdownRow]
    disagreement_penalty_applied: float
    risk_manager_override: RiskManagerOverride
    suggested_holding_period: HoldingPeriod
    stop_loss: StopLoss
    profit_target: ProfitTarget
    max_position_size_currency: float
    rationale: str = Field(max_length=500)
    human_action_required: Literal[True] = True
