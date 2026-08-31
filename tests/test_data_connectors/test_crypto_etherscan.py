"""Live smoke tests against Etherscan V2. The null address
(0x0...0, Ethereum's best-known burn address) always has a defined, nonzero,
effectively-monotonic-up balance, so it's a stable fixture for the balance
call without pinning an expected value that would drift over time.
"""
from __future__ import annotations

import pytest

from data.connectors.crypto_etherscan import EtherscanSource

BURN_ADDRESS = "0x0000000000000000000000000000000000000000"


@pytest.mark.network
def test_get_eth_balance_for_burn_address():
    source = EtherscanSource()
    balance = source.get_eth_balance(BURN_ADDRESS)
    assert balance > 0


@pytest.mark.network
def test_get_eth_supply_is_in_sane_range():
    source = EtherscanSource()
    supply = source.get_eth_supply()
    assert 1e8 < supply < 3e8
