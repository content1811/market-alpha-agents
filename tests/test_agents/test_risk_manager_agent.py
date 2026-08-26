"""Agent-level tests for RiskManagerAgent -- thin wrapper, no LLM, so these
mostly confirm correct schema assembly around signals/risk.py (already
covered in depth by tests/test_signals/test_risk.py)."""
from __future__ import annotations

from agents.risk_manager_agent import build_verdict
from data.schema import AssetClass


def test_risk_manager_agent_approve_case():
    verdict = build_verdict(equity=100_000, entry_price=100, atr14=2, stop_multiple=2, asset_class=AssetClass.US_EQUITY)
    assert verdict.risk_signal == "approve"
    assert verdict.stop_loss_override is None


def test_risk_manager_agent_jp_veto_case():
    verdict = build_verdict(
        equity=100_000, entry_price=3000, atr14=50, stop_multiple=2, asset_class=AssetClass.JP_EQUITY, prev_close=3000
    )
    assert verdict.risk_signal == "veto"
    assert verdict.structural_feasibility == "infeasible_lot_size"


def test_risk_manager_agent_stop_override_populated():
    verdict = build_verdict(
        equity=1_000_000,
        entry_price=250,
        atr14=5,
        stop_multiple=1.5,
        asset_class=AssetClass.JP_EQUITY,
        proposed_stop_price=150,
        prev_close=250,
    )
    assert verdict.stop_loss_override is not None
    assert verdict.stop_loss_override.price_level == 170.0
