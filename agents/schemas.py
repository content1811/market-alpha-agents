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


class RiskManagerVerdict(BaseModel):
    """RiskManagerAgent (section_agents.md section 9) -- a gate/modifier, never
    a weighted directional vote."""

    risk_signal: RiskSignal
    conviction: float = Field(ge=0.0, le=1.0)
    max_position_size_pct_equity: float
    max_position_size_currency: float
    stop_loss_override: Optional[StopLoss] = None
    structural_feasibility: StructuralFeasibility
    jp_limit_band_flag: Optional[str] = Field(
        default=None,
        description="Set for JP tickers per rule 9 (TSE daily price-limit band / "
        "tokubetsu-kehai check): 'may_not_be_executable' or 'limit_lock_risk', "
        "else null.",
    )
    veto_reason: Optional[str] = None


class MarketRegimeVerdict(BaseModel):
    """MarketRegimeAgent (section_agents.md section 11) -- system-wide, not
    per-ticker. Consumed by RiskManagerAgent rules 3 and 6."""

    as_of_timestamp: datetime
    trailing_realized_vol_percentile: float = Field(ge=0.0, le=100.0)
    position_size_ceiling_multiplier: float = Field(
        ge=0.0, le=1.0, description="Applied on top of RiskManagerAgent's per-trade cap"
    )
    rationale: str = Field(max_length=280)
    data_quality_flag: DataQualityFlag = DataQualityFlag.OK


FinalCall = Literal["BUY", "SELL", "HOLD"]


class SupervisorVerdict(BaseModel):
    """PortfolioSupervisorAgent (section_agents.md section 10) -- deterministic
    aggregation output, computed by orchestration/aggregate.py, not another LLM
    call. rationale is the only LLM-authored field."""

    recommendation_id: str = Field(description="f'{ticker}-{as_of_date}', == LangGraph thread_id")
    ticker: str
    asset_class: AssetClass
    as_of_timestamp: datetime
    final_call: FinalCall
    blended_score: float = Field(ge=-1.0, le=1.0)
    overall_confidence: float = Field(ge=0.0, le=1.0)
    component_verdicts: dict[str, AgentVerdict]
    risk_verdict: RiskManagerVerdict
    regime_multiplier_applied: float
    override_reason: Optional[str] = None
    rationale: str
