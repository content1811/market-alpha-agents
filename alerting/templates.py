"""Alert message formats, matching the exact examples in
docs/plan/section_data_pipeline.md section 4.3 verbatim (emoji, field order,
"analysis only" disclaimer). Kept as plain string-formatting functions --
no LLM involvement, since the SupervisorVerdict/AgentVerdict rationale text
is already LLM-authored upstream; these functions just lay it out for the
channel.
"""
from __future__ import annotations

from datetime import datetime

from agents.schemas import SupervisorVerdict

CALL_EMOJI = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪️", "WATCH": "🟡"}


def format_composite_signal_alert(verdict: SupervisorVerdict, ticker_display_name: str, timezone_label: str = "JST") -> str:
    """High-severity composite signal alert (Telegram, Markdown) --
    section_data_pipeline.md section 4.3, first example."""
    emoji = CALL_EMOJI.get(verdict.final_call, "⚪️")
    drivers = "\n".join(
        f"• {row.agent}: score {row.score:+.2f} (weight {row.weight:.2f}, confidence {row.confidence:.2f})"
        for row in sorted(verdict.component_breakdown, key=lambda r: abs(r.contribution), reverse=True)[:4]
    )
    risk_line = (
        "no veto"
        if verdict.risk_manager_override == "none"
        else f"{verdict.risk_manager_override.upper()}"
    )
    stop_text = f"{verdict.stop_loss.price_level:.2f}" if verdict.stop_loss.price_level is not None else f"{verdict.stop_loss.value} ({verdict.stop_loss.method})"
    target_text = f"{verdict.profit_target.price_level:.2f}" if verdict.profit_target.price_level is not None else f"{verdict.profit_target.value} ({verdict.profit_target.method})"

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"{emoji} *{verdict.final_call} signal — {ticker_display_name}*\n"
        f"Score: {verdict.blended_score:+.2f} | Confidence: {verdict.overall_confidence:.2f} | Asset: {verdict.asset_class.value}\n\n"
        f"Drivers:\n{drivers}\n"
        f"• Risk-manager: {risk_line}\n\n"
        f"Stop: {stop_text} | Target: {target_text}\n"
        f"Suggested hold: {verdict.suggested_holding_period.min_days:.0f}–{verdict.suggested_holding_period.max_days:.0f} {verdict.suggested_holding_period.unit}\n\n"
        f"{verdict.rationale}\n\n"
        f"Generated {generated_at} {timezone_label} | This is analysis only — no order was placed."
    )


def format_filing_alert(ticker: str, form_type: str, item_description: str, filed_at: str, url: str) -> str:
    """Filing alert (Telegram) -- section_data_pipeline.md section 4.3,
    second example."""
    return (
        f"📄 *New {form_type} filed — {ticker}*\n"
        f"{item_description} | Filed {filed_at}\n"
        f"{url}\n"
        f"No sentiment/score computed yet — headline-level scoring pending."
    )


def format_squeeze_risk_alert(ticker: str, squeeze_score: float, si_pct: float, days_to_cover: float, borrow_fee_wow_pct: float) -> str:
    """Squeeze-risk flag -- section_data_pipeline.md section 4.3, third
    example."""
    return (
        f"⚠️ *Squeeze-risk watch — {ticker}*\n"
        f"Squeeze score: {squeeze_score:.2f} (SI% of float {si_pct:.0f}%, days-to-cover {days_to_cover:.1f}, "
        f"borrow fee {borrow_fee_wow_pct:+.0f}% WoW)\n"
        f"Not a directional signal — flagging elevated volatility/whipsaw risk if you're\n"
        f"considering a short, or upside-risk if considering a long entry timing."
    )


def format_eod_summary(as_of: str, lines_by_asset_class: dict[str, str], pipeline_health: str) -> str:
    """EOD summary (email/local notification) -- section_data_pipeline.md
    section 4.3, fourth example. `lines_by_asset_class` maps e.g. "US" ->
    "AAPL HOLD (0.12) | NVDA BUY (0.61, filing caution)"."""
    body_lines = [f"Daily Summary — {as_of}"]
    for asset_class, line in lines_by_asset_class.items():
        body_lines.append(f"{asset_class}: {line}")
    body_lines.append(f"Pipeline health: {pipeline_health}")
    return "\n".join(body_lines)


def format_monthly_performance_digest(
    month_label: str,
    since_inception_cagr: float,
    since_inception_sharpe: float,
    since_inception_sortino: float,
    since_inception_max_dd: float,
    trailing_3mo_cagr: float,
    trailing_3mo_sharpe: float,
    trailing_3mo_closed_trades: int,
    trailing_3mo_hit_rate: float,
) -> str:
    """Monthly performance-reality digest (email) -- section_data_pipeline.md
    section 4.3, fifth example, and the operational surfacing of
    section_risk_validation.md section 6's recalibration cadence / section 7's
    honest return-aspiration framing. Sent every month regardless of outcome."""
    return (
        f"Monthly Performance Reality Check — {month_label}\n"
        f"Realized since inception: CAGR (annualized) {since_inception_cagr:.1%} | Sharpe {since_inception_sharpe:.1f} | "
        f"Sortino {since_inception_sortino:.1f} | Max DD {since_inception_max_dd:.1%}\n"
        f"Trailing 3mo: CAGR {trailing_3mo_cagr:.1%} | Sharpe {trailing_3mo_sharpe:.1f} | "
        f"{trailing_3mo_closed_trades} closed trades | hit rate {trailing_3mo_hit_rate:.0%}\n\n"
        f"Aspiration on record: 50%+ account growth (~¥100,000 → ~¥150,000+).\n"
        f"Reality check: your realized CAGR/Sharpe above are the numbers that matter, not the\n"
        f"aspiration. Per `risk & validation` §7: 97% of persistent retail day traders in the\n"
        f"Brazilian full-population study lost money; a systematic strategy that survives years\n"
        f"typically runs Sharpe ~1-2 and CAGR ~15-40%/yr; 50%+ in months is a low-probability\n"
        f"tail outcome, not something to size or emotionally anchor on. Treat this system's\n"
        f"goal as capital preservation + demonstrated statistically-significant edge first."
    )
