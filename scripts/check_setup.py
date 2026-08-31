"""Human-facing setup readiness report -- run this any time to see exactly
which optional integrations are configured vs. still pending, what each one
unlocks, and where to register for the ones that are missing.

Deliberately separate from scripts/validate_config.py (which checks config.yaml
is structurally valid, a Phase 0 concern) -- this checks .env against every
integration this system actually knows how to use, including the alerting
channels and Phase 5 connectors that aren't referenced in config.yaml's
data_sources.api_keys block at all.

Every integration here is optional: the system runs end-to-end today with
zero of them set (yfinance/CCXT/SEC EDGAR/Alternative.me are keyless; the
LLM/Rakuten gateway is the only genuinely required credential). Exit code is
always 0 -- this is a status report, not a gate.

Usage: python scripts/check_setup.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Integration:
    env_vars: list[str]
    unlocks: str
    register_at: str
    required: bool = False


REQUIRED = [
    Integration(["RAKUTEN_API_KEY", "RAKUTEN_BASE_URL"], "the LLM (Claude via Rakuten AI Gateway) every agent's rationale-writing call needs", "-- internal gateway, see ../Server_failure/rakuten-failure-agent", required=True),
]

OPTIONAL = [
    Integration(["ALPHA_VANTAGE_API_KEY"], "fundamentals/earnings-calendar cross-check (not wired to any agent yet -- yfinance already covers earnings dates)", "https://www.alphavantage.co/support/#api-key"),
    Integration(["TWELVEDATA_API_KEY"], "US equity OHLCV fallback if yfinance breaks", "https://twelvedata.com/pricing"),
    Integration(["TIINGO_API_KEY"], "US equity OHLCV fallback if yfinance breaks", "https://www.tiingo.com/account/api/token"),
    Integration(["FINNHUB_API_KEY"], "ticker-scoped company-news headlines (merged into NewsSentimentAgent alongside RSS)", "https://finnhub.io/register"),
    Integration(["JQUANTS_API_KEY"], "JP equity reference/backtest data (free tier is 12-weeks-lagged -- never a live signal)", "https://jpx-jquants.com/en (email or Google sign-in, no card)"),
    Integration(["EDINET_SUBSCRIPTION_KEY"], "JP financial filings (EDINET)", "https://disclosure2dl.edinet-fsa.go.jp/guide/"),
    Integration(["COINGECKO_API_KEY"], "higher-rate-limit crypto market data cross-check (CCXT/Binance public already covers current needs)", "https://www.coingecko.com/en/api/pricing (free Demo key)"),
    Integration(["DUNE_API_KEY"], "CryptoOnChainAgent's addr_divergence_score (Dune active-address query) -- already configured", "https://dune.com (Settings -> API Keys)"),
    Integration(["ETHERSCAN_API_KEY"], "CryptoOnChainAgent's flow_score/whale_score (Etherscan balance snapshots) -- already configured", "https://etherscan.io/apis"),
    Integration(["DEFILLAMA_API_KEY"], "upcoming_unlock() trigger -- confirmed 2026-08-31 this is now a PAID Pro-API feature, not free", "https://defillama.com/pro (paid)"),
    Integration(["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"], "primary alert channel -- the only thing that fires when you run `review_cli.py approve`", "message @BotFather in Telegram, then GET api.telegram.org/bot<token>/getUpdates for your chat_id"),
    Integration(["DISCORD_WEBHOOK_URL"], "backup alert channel", "Discord: Server Settings -> Integrations -> Webhooks -> New Webhook -> Copy URL"),
    Integration(["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_TO_ADDRESS"], "EOD/monthly digest emails (not yet wired into run_daily_scan.py's live loop)", "Gmail: smtp.gmail.com:587 with an App Password -- https://myaccount.google.com/apppasswords"),
]


def _status_line(integration: Integration) -> tuple[bool, str]:
    import os

    missing = [v for v in integration.env_vars if not os.environ.get(v)]
    is_set = not missing
    label = "SET    " if is_set else "MISSING"
    var_list = ", ".join(integration.env_vars)
    line = f"[{label}] {var_list}\n           unlocks: {integration.unlocks}"
    if not is_set:
        line += f"\n           register: {integration.register_at}"
    return is_set, line


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")

    print("=== Required ===")
    any_required_missing = False
    for integration in REQUIRED:
        is_set, line = _status_line(integration)
        print(line)
        any_required_missing = any_required_missing or not is_set

    print("\n=== Optional (system runs without these; each unlocks one specific thing) ===")
    set_count = 0
    for integration in OPTIONAL:
        is_set, line = _status_line(integration)
        print(line)
        set_count += int(is_set)

    print(f"\n{set_count}/{len(OPTIONAL)} optional integrations configured.")
    if any_required_missing:
        print("WARNING: a required credential is missing -- agents cannot run at all until this is set.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
