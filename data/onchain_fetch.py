"""Live on-chain input assembly for CryptoOnChainAgent, combining
data/connectors/crypto_etherscan.py (balance snapshots), data/onchain_ledger.py
(the local trailing-history ledger those snapshots feed), and
data/onchain_dune.py (the active-address series) into the exact kwargs shape
agents/crypto_on_chain_agent.py's build_verdict expects.

`exchange_addresses`/`whale_addresses` default to empty: Etherscan only covers
EVM chains, so this is ETH-only regardless, and this module ships no specific
wallet addresses of its own -- correctly labeling a real exchange/whale wallet
isn't something to guess at without independent verification. Pass in
addresses you've verified yourself (e.g. via config) to get real flow_score/
whale_score; with none, those two stay None (excluded, not guessed), exactly
like mvrv/sopr_score already are today.

Dune is queried fresh each call (a few seconds, well under 1 credit per the
live cost check during data/onchain_dune.py's build) -- with only one ETH-chain
ticker in the current watchlist this is not a meaningful budget concern; a
Dune failure degrades addr_divergence_score to None rather than raising, per
the same abstain-not-guess rule as everything else in this module.
"""
from __future__ import annotations

from data.connectors.crypto_dune import DuneSource
from data.connectors.crypto_etherscan import EtherscanSource
from data.onchain_dune import fetch_eth_active_address_series
from data.onchain_ledger import compute_flow_score, compute_whale_score, record_snapshot
from signals.crypto_composite import addr_divergence_flag_score


def _addr_divergence_score(price_making_new_high: bool) -> float | None:
    try:
        series = fetch_eth_active_address_series(DuneSource())
    except Exception:
        return None
    if len(series) < 14:
        return None
    recent_avg = sum(series[-7:]) / 7
    older_avg = sum(series[-14:-7]) / 7
    if older_avg == 0:
        return None
    pct_change = (recent_avg - older_avg) / older_avg * 100
    return addr_divergence_flag_score(pct_change, price_making_new_high)


def fetch_onchain_inputs(
    exchange_addresses: list[str] | None = None,
    whale_addresses: list[str] | None = None,
    price_making_new_high: bool = False,
    ledger_db_path: str = "data/state.db",
) -> dict:
    exchange_addresses = exchange_addresses or []
    whale_addresses = whale_addresses or []

    if exchange_addresses or whale_addresses:
        etherscan = EtherscanSource()
        for address in exchange_addresses:
            record_snapshot(ledger_db_path, "exchange", address, etherscan.get_eth_balance(address))
        for address in whale_addresses:
            record_snapshot(ledger_db_path, "whale", address, etherscan.get_eth_balance(address))

    return {
        "mvrv": None,  # no free, ready-made source exists -- see signals/crypto_composite.py's compute_onchain docstring
        "sopr_score": None,
        "flow_score": compute_flow_score(ledger_db_path, exchange_addresses) if exchange_addresses else None,
        "whale_score": compute_whale_score(ledger_db_path, whale_addresses) if whale_addresses else None,
        "addr_divergence_score": _addr_divergence_score(price_making_new_high),
        "unlock_penalty": 0.0,  # BTC/ETH have no vesting schedule -- correctly 0, not "unavailable"
    }
