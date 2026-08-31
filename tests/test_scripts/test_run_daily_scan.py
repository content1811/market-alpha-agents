"""Tests for scripts/run_daily_scan.py's pure helpers. run_ticker/main were
already run live end-to-end against the real watchlist (9 real tickers,
US+JP, all logged to storage/recommendations.db) -- not re-mocked here since
that would just re-test what a live run already proved."""
from __future__ import annotations

from pathlib import Path

from scripts.run_daily_scan import REPO_ROOT, load_config, load_watchlist


def test_load_config_reads_real_config():
    config = load_config(REPO_ROOT / "config" / "config.yaml")
    assert config["risk_management"]["account_equity_jpy"] == 100_000
    assert "us_equity" in config["asset_classes"]


def test_load_watchlist_reads_real_us_watchlist():
    tickers = load_watchlist(REPO_ROOT, "config/watchlists/us_equities.yaml")
    assert "AAPL" in tickers
    assert len(tickers) >= 3
