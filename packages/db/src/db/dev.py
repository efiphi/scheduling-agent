"""Local development helpers that run as scheduling_owner. Never used by a service.

    uv run --env-file deploy/compose/.env python -m db.dev create-user --email demo@example.com

Until web login exists (step 1.9), this is how the demo user gets a row. It prints the
user id, which the google-gateway connect command needs.
"""

import argparse
import os
import sys
from uuid import UUID

from sqlalchemy import text

from db.engine import make_engine


def create_user(email: str) -> UUID:
    """Insert the user and their default settings; return the existing id if already there."""
    password = os.environ.get("OWNER_DB_PASSWORD")
    if not password:
        raise SystemExit("Set OWNER_DB_PASSWORD (see deploy/compose/.env).")
    engine = make_engine("scheduling_owner", password)
    with engine.begin() as conn:
        # The owner is not subject to Row-Level Security (migration 0002), so no user context.
        user_id = conn.execute(
            text(
                "INSERT INTO app.users (email) VALUES (lower(:email))"
                " ON CONFLICT (email) DO NOTHING RETURNING user_id"
            ),
            {"email": email},
        ).scalar_one_or_none()
        if user_id is None:
            return UUID(
                str(
                    conn.execute(
                        text("SELECT user_id FROM app.users WHERE email = lower(:email)"),
                        {"email": email},
                    ).scalar_one()
                )
            )
        conn.execute(text("INSERT INTO app.settings (user_id) VALUES (:id)"), {"id": user_id})
        return UUID(str(user_id))


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="python -m db.dev")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user", help="create a user (or show the existing id)")
    create.add_argument("--email", required=True)
    args = parser.parse_args(argv)
    if args.command == "create-user":
        print(create_user(args.email))


if __name__ == "__main__":
    main(sys.argv[1:])
