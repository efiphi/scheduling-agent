"""WhatsApp: backup numbers, and finding a user by number before any context (step 1b).

- backup_numbers: up to two numbers per user that may send the stop code (ADR-014).
  Row-Level Security like every table; the api manages them for the logged-in user.
- users.whatsapp_number becomes unique: one verified number belongs to one user.
- app.whatsapp_senders(number): a webhook arrives with only a phone number, before the
  api knows whose message it is, so no user context exists yet. This SECURITY DEFINER
  function (hardened like those in 0002) returns only ids and the sender's role: 'owner'
  for a verified number, 'backup' for a backup number. Nothing else leaves it (T13).

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SENDERS_FUNCTION = """
CREATE FUNCTION app.whatsapp_senders(p_number text)
    RETURNS TABLE (user_id uuid, role text)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = app, pg_temp
    AS $$
        SELECT u.user_id, 'owner' FROM app.users AS u WHERE u.whatsapp_number = p_number
        UNION ALL
        SELECT b.user_id, 'backup' FROM app.backup_numbers AS b WHERE b.number = p_number
    $$
"""


def upgrade() -> None:
    op.create_table(
        "backup_numbers",
        sa.Column(
            "backup_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("number ~ '^[0-9]{8,15}$'", name="backup_numbers_digits"),
        sa.ForeignKeyConstraint(["user_id"], ["app.users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("backup_id"),
        sa.UniqueConstraint("user_id", "number", name="backup_numbers_user_number"),
        schema="app",
    )
    op.create_unique_constraint(
        "users_whatsapp_number_key", "users", ["whatsapp_number"], schema="app"
    )
    op.execute("ALTER TABLE app.backup_numbers ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON app.backup_numbers"
        " USING (user_id = app.current_user_id())"
        " WITH CHECK (user_id = app.current_user_id())"
    )
    op.execute("GRANT SELECT, INSERT, DELETE ON app.backup_numbers TO api_service")

    op.execute(SENDERS_FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION app.whatsapp_senders(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.whatsapp_senders(text) TO api_service")


def downgrade() -> None:
    op.execute("DROP FUNCTION app.whatsapp_senders(text)")
    op.drop_constraint("users_whatsapp_number_key", "users", schema="app", type_="unique")
    op.drop_table("backup_numbers", schema="app")
