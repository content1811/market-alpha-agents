"""Live funding-rate/open-interest fetch for CryptoDerivativesAgent, per
docs/plan/section_agents.md section 7. Deliberately separate from
crypto_ccxt.py's CCXTSource: that class wraps a SPOT exchange instance
(ccxt.binance()), which returns an empty funding-rate history and has no
open-interest concept at all -- funding/OI are USDT-margined PERPETUAL
FUTURES data, live-verified here to need ccxt.binanceusdm() specifically
(confirmed live: ccxt.binance().fetch_funding_rate_history() returns [],
ccxt.binanceusdm()'s does not).

fetch_open_interest_history returns real historical daily OI directly (no
local snapshot ledger needed here, unlike CryptoOnChainAgent's Etherscan
balances, which have no such history endpoint on the free tier).
"""
from __future__ import annotations

import ccxt


def fetch_derivatives_inputs(symbol: str, funding_lookback: int = 10) -> dict:
    exchange = ccxt.binanceusdm()

    funding_history = exchange.fetch_funding_rate_history(symbol, limit=funding_lookback)
    if not funding_history:
        raise ValueError(f"no funding rate history returned for {symbol}")
    funding_rate_history = [entry["fundingRate"] for entry in funding_history]

    oi_history = exchange.fetch_open_interest_history(symbol, timeframe="1d", limit=2)
    if not oi_history:
        raise ValueError(f"no open interest history returned for {symbol}")
    current_oi = oi_history[-1]["openInterestAmount"]
    prior_oi = oi_history[-2]["openInterestAmount"] if len(oi_history) > 1 else current_oi

    return {
        "funding_rate_history": funding_rate_history,
        "current_oi": current_oi,
        "prior_oi": prior_oi,
    }


if __name__ == "__main__":
    inputs = fetch_derivatives_inputs("BTC/USDT")
    print(f"Fetched {len(inputs['funding_rate_history'])} funding rate periods for BTC/USDT")
    print(inputs)
