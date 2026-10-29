"""Tables for Layer 1a (docs/03-architecture.md, data model).

Conventions:
- Every table has `user_id`, the column Row-Level Security filters on (T13).
- Primary keys are random UUIDs, so an id cannot be guessed from another (T10).
- Status-like columns are text with a CHECK constraint, which is easier to evolve in
  migrations than a Postgres enum.
- Child tables reference their parent through (user_id, id) composite keys, so a row can
  never point at another user's row even if application code passes the wrong id (T13).
"""

from datetime import datetime, time
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    LargeBinary,
    MetaData,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "app"

CHANNELS = ("web", "whatsapp", "whatsapp_command", "email")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(_in("status", ("active", "paused")), name="users_status"),
        CheckConstraint("email = lower(email)", name="users_email_lowercase"),
    )

    user_id: Mapped[UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    whatsapp_number: Mapped[str | None] = mapped_column(Text)
    # argon2id hash of the emergency stop code (ADR-014); never the code itself.
    stop_code_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class Settings(Base):
    __tablename__ = "settings"
    __table_args__ = (CheckConstraint(_in("updated_via", CHANNELS), name="settings_updated_via"),)

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    time_zone: Mapped[str] = mapped_column(Text, nullable=False, server_default="Asia/Jerusalem")
    # 0 = Sunday ... 6 = Saturday. Default: Sunday to Thursday.
    work_days: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger), nullable=False, server_default=text("'{0,1,2,3,4}'")
    )
    work_start: Mapped[time] = mapped_column(Time, nullable=False, server_default=text("'09:00'"))
    work_end: Mapped[time] = mapped_column(Time, nullable=False, server_default=text("'18:00'"))
    # Pending actions expire at this time on the nearest workday not yet ended (E7).
    end_of_workday: Mapped[time] = mapped_column(
        Time, nullable=False, server_default=text("'18:00'")
    )
    buffer_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("15"))
    max_meetings_per_day: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5")
    )
    default_duration_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("30")
    )
    reply_language: Mapped[str] = mapped_column(Text, nullable=False, server_default="sender")
    updated_at: Mapped[datetime] = _created_at()
    updated_via: Mapped[str] = mapped_column(Text, nullable=False, server_default="web")


class GoogleCredentials(Base):
    """Only google-gateway may read or write this table (invariant 1, T16)."""

    __tablename__ = "google_credentials"
    __table_args__ = (
        CheckConstraint(
            _in("status", ("connected", "expired", "revoked")), name="google_credentials_status"
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    # Encrypted by google-gateway with a key kept outside the database.
    encrypted_refresh_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="connected")
    updated_at: Mapped[datetime] = _created_at()
    # Where Gmail polling left off (ADR-003). NULL until the first poll.
    gmail_history_id: Mapped[str | None] = mapped_column(Text)


class Thread(Base):
    __tablename__ = "threads"
    __table_args__ = (
        UniqueConstraint("user_id", "gmail_thread_id", name="threads_user_gmail_thread"),
        UniqueConstraint("user_id", "thread_id", name="threads_user_thread"),
        CheckConstraint(
            _in("state", ("open", "proposed", "scheduled", "cancelled", "closed")),
            name="threads_state",
        ),
    )

    thread_id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    gmail_thread_id: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    # Addresses already in the thread; the policy guard compares recipients against this (T5).
    participants: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _created_at()


ACTION_KINDS = (
    "reply_with_slots",
    "create_event",
    "reschedule_event",
    "cancel_event",
    "block_time",
)
ACTION_STATUSES = ("pending", "approved", "rejected", "expired", "executing", "executed", "failed")


class PendingAction(Base):
    """The exact action awaiting approval. Its content and hash never change after creation (T3)."""

    __tablename__ = "pending_actions"
    __table_args__ = (
        UniqueConstraint("user_id", "action_id", name="pending_actions_user_action"),
        ForeignKeyConstraint(
            ["user_id", "thread_id"],
            ["threads.user_id", "threads.thread_id"],
            name="pending_actions_thread_same_user",
            ondelete="CASCADE",
        ),
        CheckConstraint(_in("kind", ACTION_KINDS), name="pending_actions_kind"),
        CheckConstraint(_in("status", ACTION_STATUSES), name="pending_actions_status"),
        # One action per agent task: a plan delivered twice creates nothing new (E8).
        UniqueConstraint("user_id", "task_id", name="pending_actions_user_task"),
    )

    action_id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # The agent task this action came from; NULL for actions from a direct command.
    task_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    failure_reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Lets execution check "already done?" before sending, so a retry never sends twice (E8).
    idempotency_key: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("gen_random_uuid()")
    )


class Approval(Base):
    """A single-use approval record bound to one action and its hash (invariant 4, T3, T10)."""

    __tablename__ = "approvals"
    __table_args__ = (
        # One approval per action, enforced by the database, not by application code.
        UniqueConstraint("action_id", name="approvals_one_per_action"),
        ForeignKeyConstraint(
            ["user_id", "action_id"],
            ["pending_actions.user_id", "pending_actions.action_id"],
            name="approvals_action_same_user",
            ondelete="CASCADE",
        ),
        CheckConstraint(_in("channel", CHANNELS), name="approvals_channel"),
    )

    approval_id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    action_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    approved_at: Mapped[datetime] = _created_at()
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserQuestion(Base):
    """The agent could not decide and asks the user, instead of guessing (UC-M7).

    Shown in the web app (and later on WhatsApp). The question text is written by the
    agent's code or the model, so it is shown as plain text only (T19).
    """

    __tablename__ = "user_questions"
    __table_args__ = (
        UniqueConstraint("user_id", "task_id", name="user_questions_user_task"),
        ForeignKeyConstraint(
            ["user_id", "thread_id"],
            ["threads.user_id", "threads.thread_id"],
            name="user_questions_thread_same_user",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            _in("status", ("open", "answered", "dismissed")), name="user_questions_status"
        ),
    )

    question_id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    task_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    created_at: Mapped[datetime] = _created_at()
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Append-only: services may INSERT and SELECT, never UPDATE or DELETE.

    No foreign key to users: rows outlive a deleted user, anonymized (user_id cleared,
    subject_hash kept) by a separate owner-run process.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(
            _in("actor", ("api", "gateway", "agent", "user", "system")), name="audit_log_actor"
        ),
    )

    event_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    subject_hash: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = _created_at()
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    # Ids and outcomes only, never email content (T22).
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )


class SkippedEmail(Base):
    """Sender, subject and time only, kept 7 days (UC-M8, E9). Untrusted text."""

    __tablename__ = "skipped_emails"

    skipped_id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    sender: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    marked_as_request: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class SecurityEvent(Base):
    """Signature failures, unknown senders, stop-code attempts. user_id is empty when unknown."""

    __tablename__ = "security_events"

    event_id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    at: Mapped[datetime] = _created_at()
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
