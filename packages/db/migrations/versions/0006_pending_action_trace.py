"""The email's trace on its pending action (Layer 3, step 3.3).

- pending_actions.trace_parent: the W3C traceparent of the span that created the action.
  The executor continues that trace after the user approves, so one email is one trace from
  receipt to sending, with the user's decision time as a gap inside it.
  Only the exact format is accepted (version 00, 32 + 16 hex ids, flags): the column can hold
  a trace id and nothing else. google-gateway already has INSERT on the table; nobody may
  update it.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRACEPARENT_FORMAT = "^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"


def upgrade() -> None:
    op.add_column(
        "pending_actions", sa.Column("trace_parent", sa.Text(), nullable=True), schema="app"
    )
    op.create_check_constraint(
        "pending_actions_trace_parent_format",
        "pending_actions",
        f"trace_parent ~ '{TRACEPARENT_FORMAT}'",
        schema="app",
    )


def downgrade() -> None:
    op.drop_constraint(
        "pending_actions_trace_parent_format", "pending_actions", schema="app", type_="check"
    )
    op.drop_column("pending_actions", "trace_parent", schema="app")
