"""Pure-math risk-gate logic for RiskManagerAgent, per
docs/plan/section_agents.md section 9. No LLM calls -- every field in
RiskManagerVerdict is deterministic, per the plan's own rules 1-9.

IMPORTANT caveat on TSE_PRICE_LIMIT_TIERS: this is a best-effort approximation
of JPX's daily price-limit-move table (yen amount allowed to move from the
previous close, by price band), reconstructed from general knowledge of its
structure, NOT fetched from JPX's current official publication. JPX revises
these tiers periodically. Do NOT treat this table as authoritative -- verify
against JPX's current published price-limit table
(https://www.jpx.co.jp/english/equities/trading/domestic/) before this rule
is relied on with real capital. This is flagged here rather than silently
presented as current, per the same standard applied to the FINRA Rule 4210
claim in section_risk_validation.md section 2.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# (previous_close upper bound exclusive, limit move in yen). Approximation --
# see module docstring caveat.
TSE_PRICE_LIMIT_TIERS: list[tuple[float, float]] = [
    (100, 30), (200, 50), (300, 80), (500, 100), (700, 150), (1000, 200),
    (1500, 300), (2000, 400), (3000, 500), (5000, 700), (7000, 1000),
    (10000, 1500), (15000, 2000), (20000, 3000), (30000, 4000),
    (50000, 5000), (70000, 7000), (100000, 10000),
]


def tse_price_limit_band(prev_close: float) -> tuple[float, float]:
    """Returns (lower_limit, upper_limit) for today's session given
    yesterday's close, per rule 9. Falls back to the widest tier's limit for
    prices above the table's top band."""
    limit_move = TSE_PRICE_LIMIT_TIERS[-1][1]
    for upper_bound, move in TSE_PRICE_LIMIT_TIERS:
        if prev_close < upper_bound:
            limit_move = move
            break
    return prev_close - limit_move, prev_close + limit_move


def position_size_currency(equity: float, risk_pct: float, entry_price: float, stop_price: float) -> float:
    """position_size = (equity * risk_pct) / (entry - stop), per rule 3."""
    risk_amount = equity * (risk_pct / 100)
    stop_distance = abs(entry_price - stop_price)
    if stop_distance == 0:
        return 0.0
    return risk_amount / stop_distance * entry_price  # currency notional, not share count


def kelly_upper_bound(p_win: float, avg_win_r: float, avg_loss_r: float, cap: float = 0.25) -> float:
    """Fractional Kelly upper-bound CHECK ONLY (rule 2) -- never used to size
    directly, only to sanity-check that the fixed-fractional ceiling isn't
    accidentally above what even an optimistic Kelly estimate would allow.
    Requires a validated backtest edge estimate (p_win, avg_win_r, avg_loss_r
    in R-multiples); callers with no backtest yet should not call this."""
    if avg_loss_r <= 0:
        return 0.0
    b = avg_win_r / avg_loss_r
    f_star = p_win - (1 - p_win) / b
    return max(0.0, min(f_star * cap, cap))


@dataclass
class LotFeasibility:
    feasible: bool
    shares_per_lot: int
    required_capital: float


def jp_lot_feasibility(price: float, position_size_currency_amount: float, lot_size: int = 100) -> LotFeasibility:
    """Rule 4: a full 100-share (tangen kabu) unit must be affordable within
    the risk-adjusted position size, else the trade is structurally infeasible
    (hard veto, not a silent downsize)."""
    required_capital = price * lot_size
    return LotFeasibility(
        feasible=position_size_currency_amount >= required_capital,
        shares_per_lot=lot_size,
        required_capital=required_capital,
    )


def correlation_adjusted_cap(single_trade_cap: float, correlated_open_exposure: float, cap_multiple: float = 1.5) -> float:
    """Rule 6: combined correlated exposure capped at cap_multiple x the
    single-trade risk cap. Returns the remaining currency headroom for a new
    correlated position (0 if already at/above the cap)."""
    max_combined = single_trade_cap * cap_multiple
    return max(0.0, max_combined - correlated_open_exposure)


def drawdown_adjusted_risk_pct(base_risk_pct: float, current_drawdown_pct: float, threshold_pct: float = 15.0) -> float:
    """Rule 7: halve the per-trade risk cap once trailing drawdown exceeds
    the configured threshold."""
    if current_drawdown_pct >= threshold_pct:
        return base_risk_pct / 2
    return base_risk_pct


@dataclass
class RiskGateResult:
    risk_signal: str
    conviction: float
    max_position_size_pct_equity: float
    max_position_size_currency: float
    stop_loss_override_price: float | None
    structural_feasibility: str
    jp_limit_band_flag: str | None
    veto_reason: str | None
    triggered_flags: list[str] = field(default_factory=list)


def compute_risk_verdict(
    equity: float,
    entry_price: float,
    atr14: float,
    stop_multiple: float,
    proposed_stop_price: float | None,
    asset_class: str,
    is_day_trade: bool = False,
    base_risk_pct: float = 1.0,
    regime_multiplier: float = 1.0,
    correlated_open_exposure: float = 0.0,
    correlation_cap_multiple: float = 1.5,
    current_drawdown_pct: float = 0.0,
    drawdown_threshold_pct: float = 15.0,
    prev_close: float | None = None,  # JP tickers only
    limit_lock_proximity_pct: float = 3.0,
) -> RiskGateResult:
    """Implements section_agents.md section 9's rules 1, 3, 4, 6, 7, 8, 9.
    Rule 2 (Kelly) is exposed as `kelly_upper_bound` above but not invoked
    here -- it needs a validated backtest edge estimate that doesn't exist
    until Phase 4. Rule 5 (US margin/PDT) is a config-driven assumption
    (cash-account/T+1 by default per the plan) rather than a live broker
    check, since no broker integration exists in this system by design."""
    triggered_flags: list[str] = []

    # Rule 7: drawdown circuit breaker
    risk_pct = drawdown_adjusted_risk_pct(base_risk_pct, current_drawdown_pct, drawdown_threshold_pct)
    if risk_pct < base_risk_pct:
        triggered_flags.append(f"drawdown_circuit_breaker (drawdown={current_drawdown_pct:.1f}%)")

    # Rule 3: volatility-adjusted sizing x MarketRegimeAgent multiplier (stacking, not replacing)
    stop_distance = stop_multiple * atr14
    stop_price = entry_price - stop_distance  # long-side convention; caller flips sign for shorts
    base_size = position_size_currency(equity, risk_pct, entry_price, stop_price)
    sized_position = base_size * regime_multiplier
    if regime_multiplier < 1.0:
        triggered_flags.append(f"market_regime_breaker (multiplier={regime_multiplier:.2f})")

    # Rule 6: correlation cap x MarketRegimeAgent multiplier (stacking, not replacing)
    single_trade_cap = equity * (risk_pct / 100)
    correlation_headroom = correlation_adjusted_cap(single_trade_cap, correlated_open_exposure, correlation_cap_multiple)
    correlation_headroom *= regime_multiplier
    if correlated_open_exposure > 0 and correlation_headroom < sized_position:
        triggered_flags.append("correlation_cap")
        sized_position = min(sized_position, correlation_headroom)

    # Rule 4: JP structural feasibility (hard gate)
    structural_feasibility = "ok"
    if asset_class == "jp_equity":
        lot = jp_lot_feasibility(entry_price, sized_position)
        if not lot.feasible:
            structural_feasibility = "infeasible_lot_size"

    # Rule 9: JP daily price-limit band
    jp_limit_band_flag: str | None = None
    stop_loss_override_price: float | None = None
    if asset_class == "jp_equity" and prev_close is not None:
        lower, upper = tse_price_limit_band(prev_close)
        jp_limit_band_flag = "none"
        if proposed_stop_price is not None and not (lower <= proposed_stop_price <= upper):
            # widen the stop back inside the band -- may only tighten another
            # agent's stop elsewhere in the pipeline, never loosen it beyond
            # what the band allows to fill.
            stop_loss_override_price = lower if proposed_stop_price < lower else upper
            jp_limit_band_flag = "stop_outside_band"
            triggered_flags.append("jp_stop_outside_band")
        band_width = upper - lower
        if band_width > 0:
            distance_to_lower_pct = abs(entry_price - lower) / band_width * 100
            distance_to_upper_pct = abs(upper - entry_price) / band_width * 100
            if min(distance_to_lower_pct, distance_to_upper_pct) <= limit_lock_proximity_pct:
                jp_limit_band_flag = "limit_lock_risk"
                triggered_flags.append("jp_limit_lock_risk")
                sized_position *= 0.5  # halve proposed size near a limit-lock day

    # Rule 8 + rule 4's hard gate: conviction-to-avoid from triggered flags
    conviction = 0.0
    if structural_feasibility != "ok":
        conviction = 1.0  # hard veto, not a soft score
    else:
        if "drawdown_circuit_breaker" in " ".join(triggered_flags):
            conviction += 0.3
        if "jp_limit_lock_risk" in triggered_flags:
            conviction += 0.3
        if "jp_stop_outside_band" in triggered_flags:
            conviction += 0.2
        if "correlation_cap" in triggered_flags:
            conviction += 0.2
        conviction = min(conviction, 1.0)

    if structural_feasibility != "ok":
        risk_signal = "veto"
        veto_reason = f"structurally infeasible: {structural_feasibility}"
    elif conviction > 0.7:
        risk_signal = "veto"
        veto_reason = f"risk conviction {conviction:.2f} exceeds 0.7 veto threshold: {', '.join(triggered_flags)}"
    elif triggered_flags:
        risk_signal = "reduce_size"
        veto_reason = None
    else:
        risk_signal = "approve"
        veto_reason = None

    max_pct_equity = 0.0 if risk_signal == "veto" else (sized_position / equity * 100)

    return RiskGateResult(
        risk_signal=risk_signal,
        conviction=conviction,
        max_position_size_pct_equity=max_pct_equity,
        max_position_size_currency=0.0 if risk_signal == "veto" else sized_position,
        stop_loss_override_price=stop_loss_override_price,
        structural_feasibility=structural_feasibility,
        jp_limit_band_flag=jp_limit_band_flag,
        veto_reason=veto_reason,
        triggered_flags=triggered_flags,
    )
