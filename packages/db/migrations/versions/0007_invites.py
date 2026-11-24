"""Invites: joining by a single-use, expiring link bound to one email address (UC-A1, T14).

- invites: one row per invite. user_id is the admin who sent it, so Row-Level Security
  shows each admin only their own invites, like every other table (invariant 7).
  The link's token is never stored: only its SHA-256, so a database dump holds no usable
  link. An INSERT also needs the inviter to be an admin, checked by Postgres itself, so a
  bug in the api cannot let an ordinary user invite anyone.
- The api may create an invite and revoke it (revoked_at). It cannot mark one used: only
  app.accept_invite does that, in the same transaction that creates the user.
- app.invite_email(hash): before login there is no user context, so a SECURITY DEFINER
  function (hardened like those in 0002) answers "which address is this invite for", and
  only for a live invite (unused, not revoked, not expired).
- app.accept_invite(hash, email): locks the invite row, checks it is live and bound to this
  verified email, then creates the user and their settings and marks the invite used, all
  in one transaction. Two logins racing with one link: the second waits on the lock, then
  finds the invite used. Returns the new user's id, or NULL for any refusal.
- app.admin_users(): the admin screen's list. Admins see that other users exist and their
  setup state (WhatsApp verified, Google connected), never their data (docs/04-web-app.md).

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Inserting needs an admin: the subquery runs under api_service's own RLS on users, so it
# can only ever see the caller's own row.
INSERT_POLICY = """
CREATE POLICY admin_insert ON app.invites FOR INSERT
    WITH CHECK (
        user_id = app.current_user_id()
        AND EXISTS (
            SELECT 1 FROM app.users AS u
            WHERE u.user_id = app.current_user_id() AND u.is_admin
        )
    )
"""

INVITE_EMAIL_FUNCTION = """
CREATE FUNCTION app.invite_email(p_token_hash text) RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = app, pg_temp
    AS $$ SELECT i.email FROM app.invites AS i WHERE i.token_hash = p_token_hash AND
          i.used_at IS NULL AND i.revoked_at IS NULL AND i.expires_at > now() $$
"""

ACCEPT_INVITE_FUNCTION = """
CREATE FUNCTION app.accept_invite(p_token_hash text, p_email text) RETURNS uuid
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = app, pg_temp
    AS $$
DECLARE
    v_invite uuid;
    v_user uuid;
BEGIN
    SELECT i.invite_id INTO v_invite FROM app.invites AS i
        WHERE i.token_hash = p_token_hash AND i.email = lower(p_email)
          AND i.used_at IS NULL AND i.revoked_at IS NULL AND i.expires_at > now()
        FOR UPDATE;
    IF v_invite IS NULL THEN
        RETURN NULL;
    END IF;
    INSERT INTO app.users (email) VALUES (lower(p_email))
        ON CONFLICT (email) DO NOTHING RETURNING user_id INTO v_user;
    IF v_user IS NULL THEN
        RETURN NULL;  -- already a user: they log in normally, the invite stays unused
    END IF;
    INSERT INTO app.settings (user_id) VALUES (v_user);
    UPDATE app.invites SET used_at = now(), used_by = v_user WHERE invite_id = v_invite;
    INSERT INTO app.audit_log (user_id, actor, action, details)
        VALUES (v_user, 'api', 'invite_accepted', jsonb_build_object('invite_id', v_invite));
    RETURN v_user;
END
$$
"""

ADMIN_USERS_FUNCTION = """
CREATE FUNCTION app.admin_users()
    RETURNS TABLE (
        email text, status text, is_admin boolean, whatsapp_verified boolean,
        google_status text, created_at timestamptz
    )
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = app, pg_temp
    AS $$
        SELECT u.email, u.status, u.is_admin, u.whatsapp_number IS NOT NULL,
               coalesce(g.status, 'not_connected'), u.created_at
        FROM app.users AS u
        LEFT JOIN app.google_credentials AS g USING (user_id)
        WHERE EXISTS (
            SELECT 1 FROM app.users AS me
            WHERE me.user_id = app.current_user_id() AND me.is_admin
        )
        ORDER BY u.created_at
    $$
"""

FUNCTIONS = {
    "app.invite_email(text)": INVITE_EMAIL_FUNCTION,
    "app.accept_invite(text, text)": ACCEPT_INVITE_FUNCTION,
    "app.admin_users()": ADMIN_USERS_FUNCTION,
}


def upgrade() -> None:
    op.create_table(
        "invites",
        sa.Column(
            "invite_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by", sa.UUID(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("email = lower(email)", name="invites_email_lowercase"),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="invites_token_hash_sha256"),
        sa.ForeignKeyConstraint(["user_id"], ["app.users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["used_by"], ["app.users.user_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("invite_id"),
        sa.UniqueConstraint("token_hash", name="invites_token_hash_key"),
        schema="app",
    )
    op.execute("ALTER TABLE app.invites ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_read ON app.invites FOR SELECT"
        " USING (user_id = app.current_user_id())"
    )
    op.execute(INSERT_POLICY)
    op.execute(
        "CREATE POLICY tenant_update ON app.invites FOR UPDATE"
        " USING (user_id = app.current_user_id())"
        " WITH CHECK (user_id = app.current_user_id())"
    )
    op.execute("GRANT SELECT, INSERT ON app.invites TO api_service")
    op.execute("GRANT UPDATE (revoked_at) ON app.invites TO api_service")

    for signature, body in FUNCTIONS.items():
        op.execute(body)
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO api_service")


def downgrade() -> None:
    for signature in FUNCTIONS:
        op.execute(f"DROP FUNCTION {signature}")
    op.drop_table("invites", schema="app")
