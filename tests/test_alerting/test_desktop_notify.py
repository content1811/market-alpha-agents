"""Tests for alerting/desktop_notify.py. A real notification with embedded
quotes was already sent live and confirmed to display correctly -- this
covers the escaping logic itself plus graceful failure handling."""
from __future__ import annotations

from alerting.desktop_notify import _applescript_string_literal, send_desktop_notification


def test_applescript_string_literal_escapes_double_quotes():
    # AppleScript has no single-quote string form (verified live: syntax
    # error) -- must produce a valid double-quoted literal even when the
    # input itself contains double quotes.
    assert _applescript_string_literal('He said "hello"') == '"He said \\"hello\\""'


def test_applescript_string_literal_escapes_backslashes():
    assert _applescript_string_literal("path\\to\\file") == '"path\\\\to\\\\file"'


def test_send_desktop_notification_handles_missing_osascript_gracefully(monkeypatch):
    import subprocess

    def raise_not_found(*args, **kwargs):
        raise FileNotFoundError("no such command")

    monkeypatch.setattr(subprocess, "run", raise_not_found)
    assert send_desktop_notification("title", "message") is False
