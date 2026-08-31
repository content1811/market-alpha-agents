"""Tests for scripts/check_setup.py -- pure reporting logic, no env mutation
of the real .env (uses os.environ directly via monkeypatch)."""
from __future__ import annotations

from scripts.check_setup import OPTIONAL, REQUIRED, _status_line


def test_status_line_reports_missing_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    integration = next(i for i in OPTIONAL if "TELEGRAM_BOT_TOKEN" in i.env_vars)

    is_set, line = _status_line(integration)

    assert is_set is False
    assert "MISSING" in line
    assert "register:" in line


def test_status_line_reports_set_when_all_env_vars_present(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "y")
    integration = next(i for i in OPTIONAL if "TELEGRAM_BOT_TOKEN" in i.env_vars)

    is_set, line = _status_line(integration)

    assert is_set is True
    assert "SET" in line
    assert "register:" not in line


def test_required_integration_list_is_nonempty():
    assert len(REQUIRED) >= 1
    assert all(i.required for i in REQUIRED)
