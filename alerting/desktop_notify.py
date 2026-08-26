"""macOS local notification channel, per section_data_pipeline.md section 4.2:
used for the EOD summary and pre-market scan completion, since the operator
is expected to be at the machine at those times. Confirmed working in Phase 0.
"""
from __future__ import annotations

import subprocess


def _applescript_string_literal(text: str) -> str:
    """AppleScript string literals are double-quoted only (no single-quote
    form) -- verified live: `display notification 'x'` is a syntax error.
    Escape backslashes and double quotes, then wrap in double quotes."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def send_desktop_notification(title: str, message: str, subtitle: str | None = None) -> bool:
    """Returns True if osascript ran successfully, False otherwise (never
    raises -- a failed local notification should not crash a scheduled run)."""
    script = f"display notification {_applescript_string_literal(message)} with title {_applescript_string_literal(title)}"
    if subtitle:
        script += f" subtitle {_applescript_string_literal(subtitle)}"
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False
