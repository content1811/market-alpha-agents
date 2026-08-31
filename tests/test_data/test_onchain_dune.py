"""Live smoke test for data/onchain_dune.py's permanent active-address query.
Requires network access and a real DUNE_API_KEY.
"""
from __future__ import annotations

import pytest

from data.connectors.crypto_dune import DuneSource
from data.onchain_dune import fetch_eth_active_address_series


@pytest.mark.network
def test_fetch_eth_active_address_series_returns_sane_series():
    series = fetch_eth_active_address_series(DuneSource())

    assert len(series) >= 20  # ~35 calendar days expected, some slack for partial current day
    assert all(count > 0 for count in series)
