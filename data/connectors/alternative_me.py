"""Alternative.me Fear & Greed Index -- free, keyless crypto sentiment
composite (docs/plan/section_agents.md section 6 indicator references
Fear&Greed as an open-exposure/sentiment-extreme input).

VERIFIED LIVE 2026-08-31 (per this project's "verify before trust"
discipline -- this endpoint had not been checked live in this codebase
before): `curl "https://api.alternative.me/fng/?limit=3"` returned

    {
      "name": "Fear and Greed Index",
      "data": [
        {"value": "62", "value_classification": "Greed",
         "timestamp": "1788134400", "time_until_update": "77614"},
        {"value": "69", "value_classification": "Greed",
         "timestamp": "1788048000"},
        {"value": "68", "value_classification": "Greed",
         "timestamp": "1787961600"}
      ],
      "metadata": {"error": null}
    }

Notable real-world quirks this module accounts for:
  - `value` and `timestamp` are returned as STRINGS despite being numeric;
    this module casts both to int per the requested {value: int, ...,
    timestamp} contract.
  - Only `data[0]` (today's/latest reading) carries `time_until_update`
    (seconds until the next daily refresh); older entries in the list omit
    that key entirely, so it is not part of the returned dict shape here.
  - `data` is already ordered newest-first; no client-side sorting needed.

No API key, registration, or rate-limit ledger needed -- this is a plain
function, not a DataSource subclass or a keyed *Source class, matching the
"keyless connector" half of the base.py/crypto_etherscan.py/crypto_dune.py
pattern (base.py's rate-limit/circuit-breaker machinery is for OHLCV-bar
vendors with documented per-key rate caps; this endpoint has neither).
"""
from __future__ import annotations

import requests

BASE_URL = "https://api.alternative.me/fng/"


def get_fear_greed(limit: int = 1, timeout: float = 10.0) -> list[dict]:
    """Returns up to `limit` most-recent Fear & Greed readings, newest first:
    [{"value": int, "value_classification": str, "timestamp": int}, ...].

    Raises requests.RequestException / ValueError on failure -- a connector's
    job is to fetch+normalize, not to swallow errors (callers decide
    fallback behavior); this mirrors crypto_etherscan.py/crypto_dune.py,
    not alerting/telegram_bot.py's never-raises send_X() contract, since
    this module isn't a delivery channel."""
    response = requests.get(BASE_URL, params={"limit": limit}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    return [
        {
            "value": int(entry["value"]),
            "value_classification": entry["value_classification"],
            "timestamp": int(entry["timestamp"]),
        }
        for entry in payload["data"]
    ]


if __name__ == "__main__":
    latest = get_fear_greed(limit=1)
    print(f"Fear & Greed (latest): {latest}")
