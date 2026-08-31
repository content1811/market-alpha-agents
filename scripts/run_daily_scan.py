"""Production entrypoint for the daily scan (US/JP equity + crypto), per
docs/plan/section_orchestration.md section 3 Phase 6: "full graph runs
against live (delayed/free-tier) data daily, writes every recommendation +
component breakdown to storage/recommendations.db, but the human manually
'papers' the trade... rather than real capital."

This is the piece that ties Phases 1-5 together into one runnable pass; it is
NOT yet scheduled (see scheduler/jobs.py) or gated behind the Phase 6 paper-
trading clock -- running this script does not mean Phase 6 has started, only
that its entrypoint exists.

Crypto tickers fetch OHLCV via CCXTSource (Binance spot), funding-rate/OI via
data/connectors/crypto_derivatives_live.py (Binance USDT-margined futures --
a different market type, verified live to be the only one that actually
returns funding history), and on-chain inputs via data/onchain_fetch.py.
config.yaml's crypto_onchain.exchange_addresses/whale_addresses default to
empty (see that module's docstring for why this codebase ships no specific
wallet addresses of its own) -- flow_score/whale_score stay excluded until an
operator adds real, independently-verified addresses there.

This script never sends a Telegram/desktop alert itself. Every run of
orchestration/graph.py now pauses at approval_gate_node before END (Phase 7's
interrupt()/human-approval gate) -- this script only gets as far as a
populated (but not yet human-decided) supervisor_verdict, logs it to
storage/recommendations.db, and prints which recommendations crossed a real
trigger threshold and are therefore worth reviewing. Sending an alert (or
not) is exclusively ui/review_cli.py's approve|reject flow's job -- see that
module's docstring for why this split exists.

Usage: python scripts/run_daily_scan.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.market_regime_agent import build_verdict as regime_build_verdict  # noqa: E402
from agents.schemas import SupervisorVerdict  # noqa: E402
from alerting.desktop_notify import send_desktop_notification  # noqa: E402
from alerting.templates import format_eod_summary  # noqa: E402
from alerting.triggers import AlertDeduplicator, composite_score_threshold, squeeze_risk_flag, stop_target_proximity  # noqa: E402
from data.connectors.crypto_ccxt import CCXTSource  # noqa: E402
from data.connectors.crypto_derivatives_live import fetch_derivatives_inputs  # noqa: E402
from data.connectors.jp_equities_yahoo_unofficial import JPEquitiesYahooSource  # noqa: E402
from data.connectors.us_equities_yfinance import YFinanceSource  # noqa: E402
from data.onchain_fetch import fetch_onchain_inputs  # noqa: E402
from data.schema import AssetClass  # noqa: E402
from orchestration.graph import run_for_ticker  # noqa: E402
from orchestration.storage import save_recommendation  # noqa: E402

PRIMARY_SOURCE_BY_ASSET_CLASS = {
    AssetClass.US_EQUITY: YFinanceSource,
    AssetClass.JP_EQUITY: JPEquitiesYahooSource,
}
PROXY_TICKER_BY_ASSET_CLASS = {AssetClass.US_EQUITY: "SPY", AssetClass.JP_EQUITY: "1306.T"}  # "^TOPX" is NOT a valid Yahoo symbol (verified live, 404)
LOOKBACK_DAYS = 1000
NEW_HIGH_WINDOW_DAYS = 30


def load_config(config_path: Path) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_watchlist(repo_root: Path, watchlist_file: str) -> list[str]:
    with open(repo_root / watchlist_file) as f:
        data = yaml.safe_load(f)
    return [entry["symbol"] for entry in data["symbols"]]


def run_ticker(ticker: str, asset_class: AssetClass, equity: float, regime_multiplier: float, as_of_date: str, dedup: AlertDeduplicator) -> tuple[SupervisorVerdict, str]:
    source = PRIMARY_SOURCE_BY_ASSET_CLASS[asset_class]()
    proxy_source = YFinanceSource()  # proxy indices/ETFs (SPY/1306.T) are always fetched via plain yfinance

    bars = source.get_ohlcv(ticker, lookback_days=LOOKBACK_DAYS)
    proxy_bars = proxy_source.get_ohlcv(PROXY_TICKER_BY_ASSET_CLASS[asset_class], lookback_days=LOOKBACK_DAYS)

    checkpoint_conn = sqlite3.connect(str(REPO_ROOT / "orchestration" / "checkpoints.db"), check_same_thread=False)
    from langgraph.checkpoint.sqlite import SqliteSaver

    checkpointer = SqliteSaver(checkpoint_conn)

    final_state = run_for_ticker(
        ticker, asset_class, bars, proxy_bars, equity=equity, as_of_date=as_of_date,
        regime_multiplier=regime_multiplier, checkpointer=checkpointer,
    )
    checkpoint_conn.close()

    verdict = SupervisorVerdict.model_validate(final_state["supervisor_verdict"])
    save_recommendation(str(REPO_ROOT / "storage" / "recommendations.db"), verdict)

    vol_row = next((v for v in final_state["verdicts"] if v["agent_name"] == "VolatilityVolumeAgent"), None)
    squeeze_row = next((v for v in final_state["verdicts"] if v["agent_name"] == "ShortSqueezeAgent"), None)
    atr14 = vol_row["sub_scores"].get("atr14", 0.0) if vol_row else 0.0
    last_price = bars[-1].close

    triggers = [
        composite_score_threshold(verdict.blended_score),
        squeeze_risk_flag(squeeze_row["signal_score"]) if squeeze_row else None,
        stop_target_proximity(last_price, verdict.stop_loss.price_level, verdict.profit_target.price_level, atr14) if atr14 else None,
    ]
    # No alert is sent here -- crossing a trigger only decides whether this
    # recommendation is worth surfacing to the human at all (this run's
    # printed summary, below); sending a Telegram/desktop alert is exclusively
    # ui/review_cli.py approve's job, per the module docstring above.
    for trigger in filter(None, triggers):
        if dedup.should_send(ticker, trigger.trigger_type):
            print(f"    PENDING APPROVAL [{trigger.trigger_type}]: {trigger.detail} -- run "
                  f"`python ui/review_cli.py approve|reject {verdict.recommendation_id}`")
            dedup.record_sent(ticker, trigger.trigger_type)

    summary_line = f"{ticker} {verdict.final_call} ({verdict.blended_score:+.2f})"
    return verdict, summary_line


def run_crypto_ticker(
    ticker: str, equity: float, regime_multiplier: float, as_of_date: str, dedup: AlertDeduplicator, onchain_config: dict
) -> tuple[SupervisorVerdict, str]:
    source = CCXTSource()
    bars = source.get_ohlcv(ticker, lookback_days=LOOKBACK_DAYS)
    proxy_bars = bars  # BTC/crypto-wide proxy per market_regime_agent.py's PROXY_BY_ASSET_CLASS -- own bars are the closest available cap-weighted-basket stand-in for a non-BTC ticker

    derivatives_inputs = fetch_derivatives_inputs(ticker)
    recent_high = max(b.close for b in bars[-NEW_HIGH_WINDOW_DAYS:])
    onchain_inputs = fetch_onchain_inputs(
        exchange_addresses=onchain_config.get("exchange_addresses", []),
        whale_addresses=onchain_config.get("whale_addresses", []),
        price_making_new_high=bars[-1].close >= recent_high,
    )

    checkpoint_conn = sqlite3.connect(str(REPO_ROOT / "orchestration" / "checkpoints.db"), check_same_thread=False)
    from langgraph.checkpoint.sqlite import SqliteSaver

    checkpointer = SqliteSaver(checkpoint_conn)

    final_state = run_for_ticker(
        ticker, AssetClass.CRYPTO, bars, proxy_bars, equity=equity, as_of_date=as_of_date,
        regime_multiplier=regime_multiplier, checkpointer=checkpointer,
        crypto_funding_rate_history=derivatives_inputs["funding_rate_history"],
        crypto_current_oi=derivatives_inputs["current_oi"], crypto_prior_oi=derivatives_inputs["prior_oi"],
        crypto_onchain_inputs=onchain_inputs,
    )
    checkpoint_conn.close()

    verdict = SupervisorVerdict.model_validate(final_state["supervisor_verdict"])
    save_recommendation(str(REPO_ROOT / "storage" / "recommendations.db"), verdict)

    trigger = composite_score_threshold(verdict.blended_score)
    if trigger and dedup.should_send(ticker, trigger.trigger_type):
        print(f"    PENDING APPROVAL [{trigger.trigger_type}]: {trigger.detail} -- run "
              f"`python ui/review_cli.py approve|reject {verdict.recommendation_id}`")
        dedup.record_sent(ticker, trigger.trigger_type)

    summary_line = f"{ticker} {verdict.final_call} ({verdict.blended_score:+.2f})"
    return verdict, summary_line


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="skip alert delivery, just print what would happen")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    config = load_config(REPO_ROOT / "config" / "config.yaml")
    as_of_date = date.today().isoformat()
    equity = config["risk_management"]["account_equity_jpy"]
    dedup = AlertDeduplicator(db_path=str(REPO_ROOT / "data" / "state.db"))

    summary_lines_by_class: dict[str, list[str]] = {}

    for asset_class_key, asset_class_config in config["asset_classes"].items():
        if not asset_class_config.get("enabled"):
            continue
        tickers = load_watchlist(REPO_ROOT, asset_class_config["watchlist_file"])

        if asset_class_key == "crypto":
            proxy_bars_for_regime = CCXTSource().get_ohlcv("BTC/USDT", lookback_days=LOOKBACK_DAYS)
            regime_verdict = regime_build_verdict(AssetClass.CRYPTO, proxy_bars_for_regime)
            print(f"[crypto] regime multiplier: {regime_verdict.position_size_ceiling_multiplier}")
            onchain_config = config.get("crypto_onchain", {})
            for ticker in tickers:
                try:
                    _, summary_line = run_crypto_ticker(
                        ticker, equity, regime_verdict.position_size_ceiling_multiplier, as_of_date, dedup, onchain_config
                    )
                    summary_lines_by_class.setdefault("crypto", []).append(summary_line)
                    print(f"  {summary_line}")
                except Exception as e:
                    print(f"  {ticker}: FAILED ({e})", file=sys.stderr)
            continue

        asset_class = AssetClass(asset_class_key)
        proxy_bars_for_regime = YFinanceSource().get_ohlcv(PROXY_TICKER_BY_ASSET_CLASS[asset_class], lookback_days=LOOKBACK_DAYS)
        regime_verdict = regime_build_verdict(asset_class, proxy_bars_for_regime)
        print(f"[{asset_class_key}] regime multiplier: {regime_verdict.position_size_ceiling_multiplier}")

        for ticker in tickers:
            try:
                _, summary_line = run_ticker(
                    ticker, asset_class, equity, regime_verdict.position_size_ceiling_multiplier, as_of_date, dedup
                )
                summary_lines_by_class.setdefault(asset_class_key, []).append(summary_line)
                print(f"  {summary_line}")
            except Exception as e:
                print(f"  {ticker}: FAILED ({e})", file=sys.stderr)

    eod_message = format_eod_summary(
        as_of_date,
        {k: " | ".join(v) for k, v in summary_lines_by_class.items()},
        "scan complete",
    )
    print("\n" + eod_message)
    if not args.dry_run:
        send_desktop_notification("market-alpha-agents: Daily scan complete", f"{as_of_date} -- see terminal/log for details")

    dedup.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
