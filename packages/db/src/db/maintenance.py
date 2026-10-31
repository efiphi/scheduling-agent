"""Owner-run maintenance. Never part of a service: services have no DELETE rights.

    uv run --env-file deploy/compose/.env python -m db.maintenance purge-skipped

Skipped emails keep sender, subject and time for the daily summary, for 7 days only
(UC-M8). google-gateway can insert them but not delete them, so the cleanup runs as
scheduling_owner: daily as the Kubernetes CronJob purge-skipped, or by hand under Compose.
"""

import argparse
import os
import sys

from sqlalchemy import Engine, text

from db.engine import make_engine

SKIPPED_EMAIL_DAYS = 7


def purge_skipped_emails(engine: Engine, days: int = SKIPPED_EMAIL_DAYS) -> int:
    """Delete skipped emails older than `days`; return how many. Audited, ids-free."""
    with engine.begin() as conn:
        # The owner is not subject to Row-Level Security (migration 0002): every user's rows.
        deleted = conn.execute(
            text(
                "DELETE FROM app.skipped_emails"
                " WHERE received_at < now() - make_interval(days => :days)"
            ),
            {"days": days},
        ).rowcount
        conn.execute(
            text(
                "INSERT INTO app.audit_log (user_id, actor, action, details)"
                " VALUES (NULL, 'system', 'skipped_emails_purged',"
                " jsonb_build_object('deleted', CAST(:deleted AS integer),"
                " 'days', CAST(:days AS integer)))"
            ),
            {"deleted": deleted, "days": days},
        )
    return int(deleted)


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="python -m db.maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    purge = commands.add_parser("purge-skipped", help="delete skipped emails older than 7 days")
    purge.add_argument("--days", type=int, default=SKIPPED_EMAIL_DAYS)
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("--days must be at least 1")

    password = os.environ.get("OWNER_DB_PASSWORD")
    if not password:
        raise SystemExit("Set OWNER_DB_PASSWORD (see deploy/compose/.env).")
    engine = make_engine(
        "scheduling_owner",
        password,
        os.environ.get("DB_HOST", "127.0.0.1"),
        int(os.environ.get("DB_PORT", "5432")),
    )
    if args.command == "purge-skipped":
        print(f"deleted {purge_skipped_emails(engine, args.days)} skipped email(s)")


if __name__ == "__main__":
    main(sys.argv[1:])
