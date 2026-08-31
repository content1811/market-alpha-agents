"""Local SQLite ledger of on-chain balance snapshots, for CryptoOnChainAgent's
flow_score/whale_score sub-scores (docs/plan/section_agents.md section 6
indicators #3-4).

Etherscan's free tier has no historical-balance endpoint (balancehistory is a
paid Pro feature) -- there is no free, ready-made source for "exchange net
flow z-score vs trailing 90-day distribution" or "whale balance % change over
7/30 days". This ledger makes both computable by recording our OWN balance
snapshot on every run and building the trailing distribution locally over
time, mirroring data/connectors/base.py's RateLimiter SQLite-ledger pattern.
There is no shortcut to a mature distribution on day one -- compute_flow_score/
compute_whale_score return None (excluded, not guessed) below
MIN_HISTORY_DAYS, and signals/crypto_composite.py's compute_onchain() scales
confidence down by exactly how much of the full weighting scheme is actually
backed by real data.

Scope note on whale_score: indicator #4 is defined as a *divergence* between
whale and retail-holder balance trends, which would need a total-supply
holder-distribution breakdown this ledger doesn't have. compute_whale_score
here is the whale-balance-%-change half only, as a simplified proxy.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import numpy as np

MIN_HISTORY_DAYS = 8  # bare statistical minimum for a trailing z-score/pct-change -- see module docstring re: 90-day fidelity


def _connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS onchain_balance_snapshots "
        "(category TEXT, address TEXT, ts_utc REAL, balance_eth REAL)"
    )
    conn.commit()
    return conn


def record_snapshot(db_path: str, category: str, address: str, balance_eth: float, ts_utc: float | None = None) -> None:
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO onchain_balance_snapshots (category, address, ts_utc, balance_eth) VALUES (?, ?, ?, ?)",
        (category, address, ts_utc if ts_utc is not None else time.time(), balance_eth),
    )
    conn.commit()


def _daily_total_series(db_path: str, category: str, addresses: list[str]) -> list[tuple[int, float]]:
    """One (day_bucket, total_balance_across_addresses) point per calendar
    day, summed across all tracked addresses in `category`. Multiple
    snapshots of the same address on the same day collapse to the latest one
    (rows are read in ts_utc order, so a dict overwrite keeps the last write)
    rather than being summed together, which would double-count re-runs."""
    if not addresses:
        return []
    conn = _connect(db_path)
    placeholders = ",".join("?" * len(addresses))
    rows = conn.execute(
        f"SELECT address, ts_utc, balance_eth FROM onchain_balance_snapshots "
        f"WHERE category = ? AND address IN ({placeholders}) ORDER BY ts_utc",
        (category, *addresses),
    ).fetchall()

    latest_per_address_per_day: dict[tuple[int, str], float] = {}
    for address, ts_utc, balance_eth in rows:
        day_bucket = int(ts_utc // 86400)
        latest_per_address_per_day[(day_bucket, address)] = balance_eth

    daily_totals: dict[int, float] = {}
    for (day_bucket, _address), balance_eth in latest_per_address_per_day.items():
        daily_totals[day_bucket] = daily_totals.get(day_bucket, 0.0) + balance_eth
    return sorted(daily_totals.items())


def compute_flow_score(db_path: str, exchange_addresses: list[str]) -> float | None:
    """z-score of the most recent day's net exchange balance change vs the
    trailing distribution of daily changes, per indicator #3. Positive net
    change = inflow (bearish -- coins moving toward exchanges to sell), so
    the returned score's sign is inverted from the raw z, per the plan's own
    framing ("z>+1.5 outflow spike = +10 to +20; inflow spike = -10 to -20")."""
    series = _daily_total_series(db_path, "exchange", exchange_addresses)
    if len(series) < MIN_HISTORY_DAYS + 1:  # need N+1 points for N daily changes
        return None

    totals = np.array([total for _, total in series])
    daily_changes = np.diff(totals)
    latest_change, history = daily_changes[-1], daily_changes[:-1]
    std = float(np.std(history))
    if std == 0:
        return 0.0
    net_flow_z = (latest_change - float(np.mean(history))) / std
    return float(np.clip(-net_flow_z * 10, -20.0, 20.0))


def compute_whale_score(db_path: str, whale_addresses: list[str], window_days: int = 7) -> float | None:
    """% change in tracked whale addresses' combined balance over the
    trailing `window_days`, per indicator #4's whale-balance half (see module
    docstring re: the retail-divergence half this proxy omits)."""
    series = _daily_total_series(db_path, "whale", whale_addresses)
    if len(series) < MIN_HISTORY_DAYS:
        return None

    totals = [total for _, total in series]
    lookback = min(window_days, len(totals) - 1)
    baseline = totals[-1 - lookback]
    if baseline == 0:
        return None
    pct_change = (totals[-1] - baseline) / baseline * 100
    return float(np.clip(pct_change * 1.5, -15.0, 15.0))
