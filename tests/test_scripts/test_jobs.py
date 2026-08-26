"""Tests for scheduler/jobs.py -- job construction only, never starts the
scheduler (that's a manual/foreground action, see module docstring)."""
from __future__ import annotations

from scheduler.jobs import _cron_trigger_from_string, build_scheduler


def test_cron_trigger_parses_6_field_quartz_form():
    trigger = _cron_trigger_from_string("0 30 16 * * MON-FRI")
    assert str(trigger.fields[trigger.FIELD_NAMES.index("hour")]) == "16"
    assert str(trigger.fields[trigger.FIELD_NAMES.index("minute")]) == "30"


def test_build_scheduler_registers_daily_scan_job():
    config = {
        "system": {"timezone": "Asia/Tokyo"},
        "schedules": {"daily_scan": {"cron": "0 30 16 * * MON-FRI"}},
    }
    scheduler = build_scheduler(config)
    job = scheduler.get_job("daily_scan")
    assert job is not None
    assert job.id == "daily_scan"
