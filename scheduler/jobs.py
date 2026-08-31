"""APScheduler job definitions, per config.yaml's `schedules` block
("scheduler: apscheduler_3 -- explicitly not 4.0, still alpha as of Aug 2026").

NOT started by default -- importing this module does not run anything. Per
the same caution already applied to scheduler/com.marketalpha.dailyrun.plist:
this is scaffolding for Phase 6, not something to leave running unattended
before the operator has reviewed what it actually does (fires real Telegram/
desktop alerts and writes to storage/recommendations.db on every run).

To actually run it: `python scheduler/jobs.py` (foreground, Ctrl-C to stop)
or wire scheduler/com.marketalpha.dailyrun.plist into launchd once
comfortable leaving it unattended.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

REPO_ROOT = Path(__file__).resolve().parent.parent


def _cron_trigger_from_string(cron_expr: str) -> CronTrigger:
    """config.yaml's cron strings are 6-field (sec min hour day month
    day_of_week), matching Quartz/APScheduler's extended cron form, not the
    5-field Unix crontab form."""
    second, minute, hour, day, month, day_of_week = cron_expr.split()
    return CronTrigger(second=second, minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week)


def run_daily_scan_subprocess() -> None:
    """Runs scripts/run_daily_scan.py as a subprocess (not an in-process
    import) so a crash in one day's scan can't take the scheduler process
    down with it."""
    result = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "run_daily_scan.py")])
    if result.returncode != 0:
        print(f"run_daily_scan.py exited with code {result.returncode}", file=sys.stderr)


def build_scheduler(config: dict) -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=config["system"]["timezone"])
    daily_scan_cron = config["schedules"]["daily_scan"]["cron"]
    scheduler.add_job(run_daily_scan_subprocess, _cron_trigger_from_string(daily_scan_cron), id="daily_scan")
    return scheduler


if __name__ == "__main__":
    with open(REPO_ROOT / "config" / "config.yaml") as f:
        config = yaml.safe_load(f)
    scheduler = build_scheduler(config)
    print(f"Scheduler started (timezone={config['system']['timezone']}). Press Ctrl-C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
