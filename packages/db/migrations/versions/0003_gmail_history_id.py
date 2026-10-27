"""Where each mailbox's Gmail polling left off (ADR-003, step 1.5).

google-gateway polls Gmail's History API from the last stored historyId, so each poll
fetches only what changed. The value lives next to the token in google_credentials: the
gateway already owns that table (table-level grants cover the new column), and no other
service needs it. NULL means "not polled yet": the first poll starts from now.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "google_credentials", sa.Column("gmail_history_id", sa.Text(), nullable=True), schema="app"
    )


def downgrade() -> None:
    op.drop_column("google_credentials", "gmail_history_id", schema="app")
