"""Row-Level Security on every table, and the two controlled cross-user functions.

Every policy compares a row's user_id with app.current_user_id(), which reads the
transaction-local setting written by db.session.set_user_context (ADR-005, T13).
No setting means NULL, and NULL never equals anything: a forgotten context returns no
rows instead of every row.

RLS is ENABLEd, not FORCEd. The table owner (scheduling_owner) is therefore not subject to
it, on purpose: its credentials are used only by migrations and owner-run maintenance
(7-day cleanup, anonymization), never by a service, and the two SECURITY DEFINER functions
below need to see across users. No service owns a table or has BYPASSRLS (init/01-roles.sh),
so every service connection is filtered.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables where every row belongs to exactly one user.
OWNED_TABLES = [
    "users",
    "settings",
    "google_credentials",
    "threads",
    "pending_actions",
    "approvals",
    "skipped_emails",
]

# Tables that may also hold rows with no user (a security event from an unknown number,
# a system audit entry). Such rows can be written but are never visible to a service.
NULLABLE_USER_TABLES = ["audit_log", "security_events"]

CURRENT_USER_FUNCTION = """
CREATE FUNCTION app.current_user_id() RETURNS uuid
    LANGUAGE sql STABLE
    AS $$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$
"""

# SECURITY DEFINER functions run with the owner's rights. Hardening, as Postgres recommends:
# a fixed search_path (no object can be planted earlier in the path), and EXECUTE revoked
# from PUBLIC (by default every role may call every function) and granted to one role.
FIND_USER_FUNCTION = """
CREATE FUNCTION app.find_user_by_email(p_email text) RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = app, pg_temp
    AS $$ SELECT user_id FROM app.users WHERE email = lower(p_email) $$
"""

USERS_TO_POLL_FUNCTION = """
CREATE FUNCTION app.users_to_poll() RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = app, pg_temp
    AS $$
        SELECT u.user_id
        FROM app.users AS u
        JOIN app.google_credentials AS g USING (user_id)
        WHERE u.status = 'active' AND g.status = 'connected'
    $$
"""


def upgrade() -> None:
    op.execute(CURRENT_USER_FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION app.current_user_id() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.current_user_id() TO api_service, gateway_service")

    for table in OWNED_TABLES:
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON app.{table}"
            " USING (user_id = app.current_user_id())"
            " WITH CHECK (user_id = app.current_user_id())"
        )

    for table in NULLABLE_USER_TABLES:
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        # Read: only your own rows. Write: your own rows, or rows that belong to nobody.
        op.execute(
            f"CREATE POLICY tenant_read ON app.{table} FOR SELECT"
            " USING (user_id = app.current_user_id())"
        )
        op.execute(
            f"CREATE POLICY tenant_insert ON app.{table} FOR INSERT"
            " WITH CHECK (user_id IS NULL OR user_id = app.current_user_id())"
        )

    # Controlled exception 1: before login, api must find a user by email. Returns an id only.
    op.execute(FIND_USER_FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION app.find_user_by_email(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.find_user_by_email(text) TO api_service")

    # Controlled exception 2: every minute the gateway needs the users to poll. Ids only.
    op.execute(USERS_TO_POLL_FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION app.users_to_poll() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.users_to_poll() TO gateway_service")


def downgrade() -> None:
    op.execute("DROP FUNCTION app.users_to_poll()")
    op.execute("DROP FUNCTION app.find_user_by_email(text)")
    for table in NULLABLE_USER_TABLES:
        op.execute(f"DROP POLICY tenant_insert ON app.{table}")
        op.execute(f"DROP POLICY tenant_read ON app.{table}")
        op.execute(f"ALTER TABLE app.{table} DISABLE ROW LEVEL SECURITY")
    for table in OWNED_TABLES:
        op.execute(f"DROP POLICY tenant_isolation ON app.{table}")
        op.execute(f"ALTER TABLE app.{table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION app.current_user_id()")
