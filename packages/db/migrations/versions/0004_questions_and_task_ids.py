"""Questions to the user, and one action per agent task (step 1.8).

- user_questions: when the agent cannot decide (an unclear request, no free slot, the
  calendar did not answer), google-gateway records a question for the user instead of
  guessing (UC-M7). Row-Level Security and per-role grants like every other table (T13).
- pending_actions.task_id, unique per user: a plan delivered twice by the queue creates
  one action, enforced by the database rather than by code (E8). Same for questions.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANTS = [
    # The gateway writes questions; the api shows them and records the answer.
    "GRANT SELECT, INSERT ON app.user_questions TO gateway_service",
    "GRANT SELECT ON app.user_questions TO api_service",
    "GRANT UPDATE (status, answered_at) ON app.user_questions TO api_service",
]


def upgrade() -> None:
    op.create_table(
        "user_questions",
        sa.Column(
            "question_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("thread_id", sa.UUID(), nullable=True),
        sa.Column("task_id", sa.UUID(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('open', 'answered', 'dismissed')", name="user_questions_status"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "thread_id"],
            ["app.threads.user_id", "app.threads.thread_id"],
            name="user_questions_thread_same_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app.users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("question_id"),
        sa.UniqueConstraint("user_id", "task_id", name="user_questions_user_task"),
        schema="app",
    )
    op.add_column("pending_actions", sa.Column("task_id", sa.UUID(), nullable=True), schema="app")
    op.create_unique_constraint(
        "pending_actions_user_task", "pending_actions", ["user_id", "task_id"], schema="app"
    )

    op.execute("ALTER TABLE app.user_questions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON app.user_questions"
        " USING (user_id = app.current_user_id())"
        " WITH CHECK (user_id = app.current_user_id())"
    )
    for grant in GRANTS:
        op.execute(grant)


def downgrade() -> None:
    op.drop_constraint("pending_actions_user_task", "pending_actions", schema="app", type_="unique")
    op.drop_column("pending_actions", "task_id", schema="app")
    op.drop_table("user_questions", schema="app")
