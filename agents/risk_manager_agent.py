"""RiskManagerAgent per docs/plan/section_agents.md section 9.

No LLM call: every RiskManagerVerdict field is deterministic, computed by
signals/risk.py's rules 1/3/4/6/7/8/9. This is deliberate, not a simplification
-- the persona's whole point is being "independent of how confident the other
agents are," and the most reliable way to enforce that is to not run this
gate's decision through a language model at all.
"""
from __future__ import annotations

from agents.schemas import RiskManagerVerdict, StopLoss
from data.schema import AssetClass
from signals.risk import compute_risk_verdict


def build_verdict(
    equity: float,
    entry_price: float,
    atr14: float,
    stop_multiple: float,
    asset_class: AssetClass,
    proposed_stop_price: float | None = None,
    base_risk_pct: float = 1.0,
    regime_multiplier: float = 1.0,
    correlated_open_exposure: float = 0.0,
    correlation_cap_multiple: float = 1.5,
    current_drawdown_pct: float = 0.0,
    drawdown_threshold_pct: float = 15.0,
    prev_close: float | None = None,
    limit_lock_proximity_pct: float = 3.0,
) -> RiskManagerVerdict:
    result = compute_risk_verdict(
        equity=equity,
        entry_price=entry_price,
        atr14=atr14,
        stop_multiple=stop_multiple,
        proposed_stop_price=proposed_stop_price,
        asset_class=asset_class.value,
        base_risk_pct=base_risk_pct,
        regime_multiplier=regime_multiplier,
        correlated_open_exposure=correlated_open_exposure,
        correlation_cap_multiple=correlation_cap_multiple,
        current_drawdown_pct=current_drawdown_pct,
        drawdown_threshold_pct=drawdown_threshold_pct,
        prev_close=prev_close,
        limit_lock_proximity_pct=limit_lock_proximity_pct,
    )

    stop_override = (
        StopLoss(method="structure", value=result.stop_loss_override_price, price_level=result.stop_loss_override_price)
        if result.stop_loss_override_price is not None
        else None
    )

    return RiskManagerVerdict(
        risk_signal=result.risk_signal,
        conviction=result.conviction,
        max_position_size_pct_equity=result.max_position_size_pct_equity,
        max_position_size_currency=result.max_position_size_currency,
        stop_loss_override=stop_override,
        structural_feasibility=result.structural_feasibility,
        jp_limit_band_flag=result.jp_limit_band_flag,
        veto_reason=result.veto_reason,
    )
