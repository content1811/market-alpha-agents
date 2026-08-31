"""Unit tests for data/onchain_ledger.py -- synthetic snapshots inserted
directly (no live Etherscan calls needed here, that's covered by
tests/test_data_connectors/test_crypto_etherscan.py), hand-computed
expectations per the module's own z-score/pct-change formulas.
"""
from __future__ import annotations

import tempfile

import pytest

from data.onchain_ledger import compute_flow_score, compute_whale_score, record_snapshot

DAY = 86400.0


@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield f"{tmpdir}/onchain.db"


def _seed(db_path, category, address, totals, start_day=0):
    for i, balance in enumerate(totals):
        record_snapshot(db_path, category, address, balance, ts_utc=(start_day + i) * DAY)


def test_flow_score_none_below_min_history(db_path):
    _seed(db_path, "exchange", "0xexchange", [1000.0] * 5)
    assert compute_flow_score(db_path, ["0xexchange"]) is None


def test_flow_score_hand_computed(db_path):
    # changes = [-10, 20, -15, 10, -15, 20, -10, 30]; history (first 7) has
    # mean=0, population std=14.8804761828569; latest=30 -> z=2.0160645 ->
    # score = clip(-z*10, -20, 20) = -20.0 (clips at the boundary)
    totals = [1000.0, 990.0, 1010.0, 995.0, 1005.0, 990.0, 1010.0, 1000.0, 1030.0]
    _seed(db_path, "exchange", "0xexchange", totals)
    assert compute_flow_score(db_path, ["0xexchange"]) == pytest.approx(-20.0)


def test_flow_score_sums_across_multiple_addresses(db_path):
    # Same shape as the hand-computed case, split evenly across 2 addresses
    # -- must sum to the identical per-day totals and therefore the same score.
    totals = [1000.0, 990.0, 1010.0, 995.0, 1005.0, 990.0, 1010.0, 1000.0, 1030.0]
    _seed(db_path, "exchange", "0xa", [t / 2 for t in totals])
    _seed(db_path, "exchange", "0xb", [t / 2 for t in totals])
    assert compute_flow_score(db_path, ["0xa", "0xb"]) == pytest.approx(-20.0)


def test_same_day_snapshot_keeps_latest_not_sum(db_path):
    # Two snapshots on the same day for one address must not double-count --
    # the second (re-run) value should simply replace the first.
    record_snapshot(db_path, "exchange", "0xa", 1000.0, ts_utc=0.0)
    record_snapshot(db_path, "exchange", "0xa", 1100.0, ts_utc=1.0)  # same day_bucket (0), re-run
    for i in range(1, 9):
        record_snapshot(db_path, "exchange", "0xa", 1100.0, ts_utc=i * DAY)
    # Only day 0 (=1100, the latest same-day write) through day 8 -- flat
    # thereafter, so the trailing history is all-zero changes -> std=0 -> 0.0,
    # not a spurious jump from summing 1000+1100 on day 0.
    assert compute_flow_score(db_path, ["0xa"]) == pytest.approx(0.0)


def test_whale_score_none_below_min_history(db_path):
    _seed(db_path, "whale", "0xwhale", [1000.0] * 5)
    assert compute_whale_score(db_path, ["0xwhale"]) is None


def test_whale_score_hand_computed(db_path):
    # 8 days flat at 1000 then +5% on the last day -> pct_change=5.0 ->
    # score = clip(5.0*1.5, -15, 15) = 7.5
    totals = [1000.0] * 7 + [1050.0]
    _seed(db_path, "whale", "0xwhale", totals)
    assert compute_whale_score(db_path, ["0xwhale"]) == pytest.approx(7.5)


def test_no_addresses_returns_none(db_path):
    assert compute_flow_score(db_path, []) is None
    assert compute_whale_score(db_path, []) is None
