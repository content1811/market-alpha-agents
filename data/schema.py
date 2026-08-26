"""Canonical data models. Every connector in data/connectors/ must normalize
into these before a value is allowed to leave the raw/ staging area -- nothing
downstream ever touches a vendor-specific field name.

See docs/plan/section_data_pipeline.md section 2.2 for the design rationale,
including the mandated fully-adjusted-close convention on NormalizedBar.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AssetClass(str, Enum):
    US_EQUITY = "us_equity"
    JP_EQUITY = "jp_equity"
    CRYPTO = "crypto"


class DataQualityFlag(str, Enum):
    """Canonical propagation rule defined in section_data_pipeline.md section 2.4.

    - STALE: cached value age exceeds 2x its source's configured TTL.
      Any agent consuming it must cap its own confidence at <=0.3.
    - UNAVAILABLE: primary AND fallback both circuit-broken, no live or
      within-2xTTL cached value exists. Consuming agent must abstain
      (signal_score=0, confidence=0) and RiskManagerAgent must force HOLD.
    - PARTIAL: assembled from an incomplete batch response. Mild confidence
      penalty at the consuming agent's discretion, not a forced abstain.
    """

    OK = "ok"
    STALE = "stale"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class NormalizedBar(BaseModel):
    symbol: str
    exchange: Optional[str] = None
    asset_class: AssetClass
    ts_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    adjusted: bool = Field(
        description="True once normalized to the canonical fully-adjusted-close "
        "convention (splits and dividends both applied, matching yfinance's "
        "auto_adjust=True behavior). No agent or backtest may read a bar where "
        "this is False."
    )
    adjustment_factor: float = Field(
        default=1.0,
        description="Cumulative split/dividend multiplier applied to the vendor's "
        "raw OHLC to reach the adjusted value, kept for audit reconstruction.",
    )
    source: str
    ingested_at: datetime
    data_quality_flag: DataQualityFlag = DataQualityFlag.OK


class NormalizedFundamental(BaseModel):
    symbol: str
    period_end: datetime
    metric: str
    value: float
    unit: Optional[str] = None
    source: str
    ingested_at: datetime
    data_quality_flag: DataQualityFlag = DataQualityFlag.OK


class NormalizedNewsItem(BaseModel):
    item_id: str = Field(description="Hash of url+title, used for de-dup")
    symbol_tags: list[str] = Field(default_factory=list)
    headline: str
    summary: Optional[str] = None
    source: str
    url: str
    published_at_utc: datetime
    ingested_at: datetime


class NormalizedSignal(BaseModel):
    symbol: str
    asset_class: AssetClass
    ts_utc: datetime
    signal_name: str
    score: float = Field(ge=-1.0, le=1.0)
    weight: float
    agent: str
    params_json: str = Field(description="JSON-encoded params used to compute this signal, for audit")
