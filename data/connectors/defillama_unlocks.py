"""DefiLlama token-unlock calendar.

VERIFIED LIVE 2026-08-31 (per this project's "verify before trust"
discipline -- this endpoint had not been checked live in this codebase
before, and the real shape turned out to differ from this task's
assumption, not just cosmetically):

  - `GET https://api.llama.fi/unlocks`            -> HTTP 404 (no such path)
  - `GET https://api.llama.fi/emissions`          -> HTTP 402, body:
        "Upgrade to the paid API plan at https://defillama.com/subscription"
  - `GET https://api.llama.fi/emission/{protocol}` -> same HTTP 402
  - `GET https://pro-api.llama.fi/api/emissions` (no key) -> HTTP 500,
        body {"error": "API Key is wrong"}

Cross-checked against DefiLlama's own public OpenAPI specs (cloned from
github.com/DefiLlama/api-docs, since defillama.com/docs/api itself sits
behind a Cloudflare JS challenge that blocks non-browser clients):
`defillama-openapi-free.json` has NO unlocks/emissions path at all; the
routes (tagged "Unlocks") live exclusively in `defillama-openapi-pro.json`,
under `servers: [https://pro-api.llama.fi]`:
  - `GET /api/emissions`            -- list of every tracked token
  - `GET /api/emission/{protocol}`  -- single-token detail (vesting curve)

Conclusion: contrary to this task's "free, keyless" assumption, DefiLlama's
unlock calendar is now Pro-API-only (paid). This module is therefore a
KEYED connector (`DEFILLAMA_API_KEY`, see .env.example), following the
crypto_dune.py/crypto_etherscan.py pattern -- it raises ValueError at
construction if the key is missing, same as DuneSource/EtherscanSource.
DefiLlama's documented pro-api auth convention embeds the key in the URL
path (`https://pro-api.llama.fi/<API_KEY>/api/...`, same as their coins/
stablecoins pro endpoints) -- this has NOT been live-verified end-to-end
since no paid key is available in this environment; only the route's
existence and the 402/500 probes above were confirmed live.

Response shape used below (GET /api/emissions, per the pro OpenAPI spec --
documented, not live-observed with real data, since that requires the paid
key this environment doesn't have) is one object per tracked token:
    {"token": "coingecko:whitebit", "name": "WhiteBIT", "gecko_id": "whitebit",
     "circSupply": 293500000, "maxSupply": 375000000, "mcap": 6577845629.2,
     "events": [{"timestamp": 1659657600, "noOfTokens": [120000000],
                 "category": "noncirculating", "unlockType": "cliff",
                 "description": "..."}],
     "nextEvent": {"date": 1773360001, "toUnlock": 81500000},
     "unlocksPerDay": 0}
The schema has no ticker "symbol" field -- only `gecko_id` and `name` --
so `get_upcoming_unlocks()` matches `token_symbol` case-insensitively
against both; a real ticker like "UNI" only matches if it equals the
protocol's gecko_id or name exactly (e.g. gecko_id="uniswap", not "uni").
This is a genuine limitation of the documented schema, not a shortcut taken
here. Tested via mocked HTTP responses shaped exactly per that spec (same
precedent as alerting/telegram_bot.py mock-testing a channel with no real
credentials available).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests
from pydantic_settings import BaseSettings, SettingsConfigDict

PRO_API_BASE = "https://pro-api.llama.fi"


class DefiLlamaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    defillama_api_key: str | None = None


class DefiLlamaUnlocksSource:
    """Not OHLCV-bar-shaped (a token's unlock calendar is a list of
    scheduled vesting events, not a bar series), so this does NOT subclass
    DataSource -- same rationale as EtherscanSource/DuneSource."""

    name = "defillama_unlocks"

    def __init__(self, settings: DefiLlamaSettings | None = None, timeout: float = 15.0):
        s = settings or DefiLlamaSettings()
        if not s.defillama_api_key:
            raise ValueError(
                "DEFILLAMA_API_KEY not set -- see .env.example (DefiLlama's unlock "
                "calendar moved to the paid Pro API; there is no free tier for it)"
            )
        self._api_key = s.defillama_api_key
        self._timeout = timeout
        self._session = requests.Session()

    def _get_emissions_list(self) -> list[dict]:
        url = f"{PRO_API_BASE}/{self._api_key}/api/emissions"
        response = self._session.get(url, timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def get_upcoming_unlocks(self, token_symbol: str, within_days: int = 30) -> list[dict]:
        """Returns one dict per unlock event in [now, now+within_days] for
        the token matching `token_symbol` (see module docstring for the
        gecko_id/name matching caveat): [{"date": "YYYY-MM-DD",
        "amount_usd_or_tokens": float, "pct_of_circulating_supply":
        float | None, "category": str | None, "unlock_type": str | None}].
        Empty list if the token isn't found or has no events in-window."""
        tokens = self._get_emissions_list()
        symbol_lower = token_symbol.lower()
        match = next(
            (
                t
                for t in tokens
                if str(t.get("gecko_id", "")).lower() == symbol_lower
                or str(t.get("name", "")).lower() == symbol_lower
            ),
            None,
        )
        if match is None:
            return []

        circ_supply = match.get("circSupply") or 0
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=within_days)

        results = []
        for event in match.get("events", []) or []:
            ts = event.get("timestamp")
            if ts is None:
                continue
            event_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            if not (now <= event_dt <= cutoff):
                continue
            amount_tokens = float(sum(event.get("noOfTokens", []) or []))
            pct_of_supply = (amount_tokens / circ_supply * 100) if circ_supply else None
            results.append(
                {
                    "date": event_dt.date().isoformat(),
                    "amount_usd_or_tokens": amount_tokens,
                    "pct_of_circulating_supply": pct_of_supply,
                    "category": event.get("category"),
                    "unlock_type": event.get("unlockType"),
                }
            )
        return results


def get_upcoming_unlocks(
    token_symbol: str, within_days: int = 30, settings: DefiLlamaSettings | None = None
) -> list[dict]:
    """Module-level convenience wrapper (see DefiLlamaUnlocksSource for the
    keyed-client details this needs -- raises ValueError if DEFILLAMA_API_KEY
    is unset)."""
    return DefiLlamaUnlocksSource(settings).get_upcoming_unlocks(token_symbol, within_days)


if __name__ == "__main__":
    settings = DefiLlamaSettings()
    if not settings.defillama_api_key:
        print(
            "DefiLlama Pro API not configured (DEFILLAMA_API_KEY missing from .env) -- "
            "skipping live call. Confirmed live 2026-08-31: the free tier has NO "
            "unlocks/emissions endpoint at all (HTTP 402 'Upgrade to the paid API plan')."
        )
    else:
        unlocks = get_upcoming_unlocks("uniswap", within_days=30, settings=settings)
        print(f"Upcoming unlocks: {unlocks}")
