"""Etherscan V2 adapter -- on-chain balance/supply lookups, per the "Etherscan
V2 unified API" recommendation in docs/research/crypto_data.md section 2.
Not OHLCV-bar-shaped (a balance or supply figure is a single point-in-time
scalar, not a bar series), so this does NOT subclass DataSource; it has no
notion of lookback_days or a NormalizedBar to return.

V2 folds all EVM chains under one key via &chainid=; this adapter is scoped
to chainid=1 (Ethereum mainnet) since that's the only chain in budget.
"""
from __future__ import annotations

import requests
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_URL = "https://api.etherscan.io/v2/api"
CHAIN_ID = 1


class EtherscanSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    etherscan_api_key: str | None = None


class EtherscanSource:
    name = "etherscan"

    def __init__(self, settings: EtherscanSettings | None = None):
        s = settings or EtherscanSettings()
        if not s.etherscan_api_key:
            raise ValueError("ETHERSCAN_API_KEY not set")
        self._api_key = s.etherscan_api_key

    def _get(self, params: dict) -> str:
        resp = requests.get(
            BASE_URL,
            params={**params, "chainid": CHAIN_ID, "apikey": self._api_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if data["status"] != "1":
            raise ValueError(f"etherscan error: {data['message']}: {data.get('result')}")
        return data["result"]

    def get_eth_balance(self, address: str) -> float:
        wei = self._get(
            {"module": "account", "action": "balance", "address": address, "tag": "latest"}
        )
        return float(wei) / 1e18

    def get_eth_supply(self) -> float:
        wei = self._get({"module": "stats", "action": "ethsupply"})
        return float(wei) / 1e18


if __name__ == "__main__":
    source = EtherscanSource()
    print(f"ETH supply: {source.get_eth_supply():,.2f}")
    burn_address = "0x0000000000000000000000000000000000000000"
    print(f"Burn address balance: {source.get_eth_balance(burn_address):,.4f} ETH")
