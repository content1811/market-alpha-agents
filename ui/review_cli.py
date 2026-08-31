"""Human review CLI, per docs/plan/section_orchestration.md section 3 Phase 7.
Three separate flows, deliberately not conflated into one command:

  (a) `approve|reject <recommendation_id>` -- the pre-alert, same-day gate.
      Resumes the graph paused at orchestration/graph.py's approval_gate
      interrupt() via Command(resume=...), records the decision in
      storage/recommendations.db, and -- on approve only -- sends the
      Telegram/desktop alert. This is the *only* code path in this whole
      system that ever calls alerting/telegram_bot.py or
      alerting/desktop_notify.py with a specific trade recommendation
      (scripts/run_daily_scan.py deliberately does not, see its docstring).

  (b) `log-outcome <ticker> <date>` -- invoked any time later, once the human
      has actually (or decidedly not) traded. Reconstructs recommendation_id
      as f"{ticker}-{date}" (matching orchestration/graph.py's thread_id
      convention) and appends to storage/outcomes.db.

  (c) `pending-outcomes --older-than <Nd>` -- reporting only: approved
      recommendations older than N days with no logged outcome yet.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from alerting.desktop_notify import send_desktop_notification  # noqa: E402
from alerting.discord_bot import send_discord_message  # noqa: E402
from alerting.telegram_bot import send_telegram_message  # noqa: E402
from alerting.templates import format_composite_signal_alert  # noqa: E402
from agents.schemas import SupervisorVerdict  # noqa: E402
from orchestration.graph import resume_for_ticker  # noqa: E402
from orchestration.storage import (  # noqa: E402
    get_recommendation,
    pending_outcomes,
    save_outcome,
    update_human_decision,
)

RECOMMENDATIONS_DB = str(REPO_ROOT / "storage" / "recommendations.db")
OUTCOMES_DB = str(REPO_ROOT / "storage" / "outcomes.db")
CHECKPOINTS_DB = str(REPO_ROOT / "orchestration" / "checkpoints.db")


def _decide(recommendation_id: str, decision: str) -> int:
    row = get_recommendation(RECOMMENDATIONS_DB, recommendation_id)
    if row is None:
        print(f"No recommendation found for {recommendation_id!r} in {RECOMMENDATIONS_DB}", file=sys.stderr)
        return 1
    if row["human_decision"] is not None:
        print(f"{recommendation_id} was already {row['human_decision']!r} -- not resuming a second time.", file=sys.stderr)
        return 1

    verdict = SupervisorVerdict.model_validate_json(row["full_verdict_json"])
    print(f"{recommendation_id}: {verdict.final_call} (score {verdict.blended_score:+.2f}, "
          f"confidence {verdict.overall_confidence:.2f})\n{verdict.rationale}")

    conn = sqlite3.connect(CHECKPOINTS_DB, check_same_thread=False)
    from langgraph.checkpoint.sqlite import SqliteSaver

    final_state = resume_for_ticker(recommendation_id, decision, SqliteSaver(conn))
    conn.close()
    if final_state.get("human_decision") != decision:
        print(f"Resume did not take effect as expected (got human_decision={final_state.get('human_decision')!r})", file=sys.stderr)
        return 1

    update_human_decision(RECOMMENDATIONS_DB, recommendation_id, decision)

    if decision == "approved":
        message = format_composite_signal_alert(verdict, verdict.ticker)
        telegram_ok = send_telegram_message(message)
        discord_ok = send_discord_message(message)  # backup channel, per section_data_pipeline.md section 4.2
        desktop_ok = send_desktop_notification(f"market-alpha-agents: {verdict.final_call} {verdict.ticker}", verdict.rationale)
        print(f"Approved and alerted (telegram={telegram_ok}, discord={discord_ok}, desktop={desktop_ok}).")
    else:
        print("Rejected -- no alert sent.")
    return 0


def _log_outcome(args: argparse.Namespace) -> int:
    recommendation_id = f"{args.ticker}-{args.date}"
    row = get_recommendation(RECOMMENDATIONS_DB, recommendation_id)
    if row is None:
        print(f"No recommendation found for {recommendation_id!r} in {RECOMMENDATIONS_DB}", file=sys.stderr)
        return 1
    if row["human_decision"] != "approved":
        print(f"{recommendation_id} was never approved (human_decision={row['human_decision']!r}) -- refusing to log an outcome for it.", file=sys.stderr)
        return 1

    save_outcome(
        OUTCOMES_DB,
        recommendation_id,
        actual_entry_price=args.actual_entry_price,
        actual_exit_price=args.actual_exit_price,
        exit_date=args.exit_date,
        exit_reason=args.exit_reason,
        human_action=args.human_action,
        realized_pnl=args.realized_pnl,
    )
    print(f"Logged outcome for {recommendation_id}.")
    return 0


def _pending_outcomes(args: argparse.Namespace) -> int:
    rows = pending_outcomes(RECOMMENDATIONS_DB, OUTCOMES_DB, older_than_days=args.older_than)
    if not rows:
        print("No approved recommendations are missing an outcome.")
        return 0
    for row in rows:
        print(f"{row['recommendation_id']}: {row['ticker']} {row['final_call']} (as of {row['as_of_timestamp']}) -- no outcome logged")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="review_cli.py")
    sub = parser.add_subparsers(dest="command", required=True)

    approve_p = sub.add_parser("approve")
    approve_p.add_argument("recommendation_id")

    reject_p = sub.add_parser("reject")
    reject_p.add_argument("recommendation_id")

    log_p = sub.add_parser("log-outcome")
    log_p.add_argument("ticker")
    log_p.add_argument("date")
    log_p.add_argument("--actual-entry-price", type=float, default=None)
    log_p.add_argument("--actual-exit-price", type=float, default=None)
    log_p.add_argument("--exit-date", default=None)
    log_p.add_argument("--exit-reason", default=None, choices=["target_hit", "stop_hit", "time_stop", "discretionary"])
    log_p.add_argument("--human-action", required=True, choices=["followed", "modified", "ignored"])
    log_p.add_argument("--realized-pnl", type=float, default=None)

    pending_p = sub.add_parser("pending-outcomes")
    pending_p.add_argument("--older-than", type=float, default=90, help="days, e.g. --older-than 90")

    args = parser.parse_args()
    if args.command == "approve":
        return _decide(args.recommendation_id, "approved")
    if args.command == "reject":
        return _decide(args.recommendation_id, "rejected")
    if args.command == "log-outcome":
        return _log_outcome(args)
    if args.command == "pending-outcomes":
        return _pending_outcomes(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
