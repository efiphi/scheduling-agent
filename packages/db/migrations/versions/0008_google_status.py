"""The api may learn whether the user's Google account is connected, and nothing more.

The web app must show "connect Google" or "Google needs reconnecting", but the api has no
grant on app.google_credentials at all: that table holds the encrypted refresh tokens, and
only google-gateway may touch it (invariant 1, T16). This SECURITY DEFINER function
(hardened like those in 0002) returns one word for the current user context:
connected, expired, revoked, or not_connected. No token, scope or date leaves it.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GOOGLE_STATUS_FUNCTION = """
CREATE FUNCTION app.google_status() RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = app, pg_temp
    AS $$
        SELECT coalesce(
            (SELECT g.status FROM app.google_credentials AS g
             WHERE g.user_id = app.current_user_id()),
            'not_connected'
        )
    $$
"""


def upgrade() -> None:
    op.execute(GOOGLE_STATUS_FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION app.google_status() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.google_status() TO api_service")


def downgrade() -> None:
    op.execute("DROP FUNCTION app.google_status()")
