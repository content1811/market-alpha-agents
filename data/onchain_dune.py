"""Dune-backed feed for CryptoOnChainAgent's addr_divergence sub-score
(docs/plan/section_agents.md section 6 indicator #5).

Real MVRV/SOPR need realized-cap/UTXO-cost-basis computation over the full
chain history -- a "real engineering lift" per section 6's own note, not
something to fabricate a plausible-looking SQL query for. Daily active
address counts are a different, much simpler aggregation (COUNT DISTINCT
sender per day) that Dune's decoded ethereum.transactions table answers
correctly and cheaply -- live-verified during this connector's build: a
35-day window costs well under 1 credit and returns in a few seconds.

QUERY_ID below is a permanent (not the ephemeral smoke-test) private query
already created in this project's Dune workspace, named "market-alpha-agents:
ETH daily active addresses (35d)". To recreate it elsewhere:
    DuneSource().create_query(
        "market-alpha-agents: ETH daily active addresses (35d)",
        "SELECT date_trunc('day', block_time) as d, COUNT(DISTINCT \"from\") as active "
        "FROM ethereum.transactions WHERE block_time > now() - interval '35' day GROUP BY 1 ORDER BY 1",
    )
"""
from __future__ import annotations

from data.connectors.crypto_dune import DuneSource

ETH_ACTIVE_ADDRESSES_QUERY_ID = 8560151


def fetch_eth_active_address_series(dune: DuneSource) -> list[float]:
    """Trailing ~35 daily active-address counts, oldest to newest."""
    execution_id = dune.execute_query(ETH_ACTIVE_ADDRESSES_QUERY_ID)
    rows = dune.get_execution_results(execution_id)
    rows.sort(key=lambda row: row["d"])
    return [float(row["active"]) for row in rows]
