"""Security events as signals for detection (Layer 5, ADR-022).

Every security event the services write to `app.security_events` is also counted here and
logged, so detection rules can run on it without reading the database:

    sa_security_events_total{kind="stop_code_failed"}   in Prometheus, for alert rules
    {"msg": "security event: kind=stop_code_failed ..."}  in Loki, to investigate

Rules on the counter are unit-tested in CI with promtool. The database row stays the record
of what happened, for the user and for audit.

`kind` is the only attribute, from the fixed list below, so the number of series stays small
and nothing personal reaches a metric (T22). A kind missing from the list is counted as
"unlisted", and tests/test_security_events.py fails until it is added.
"""

import logging
from uuid import UUID

from shared import metrics

logger = logging.getLogger("security")

# Every kind, and the threats it is evidence of (docs/02-threat-model.md).
KINDS: dict[str, tuple[str, ...]] = {
    # WhatsApp
    "whatsapp_bad_signature": ("T9",),
    "whatsapp_unknown_sender": ("T8",),
    "whatsapp_number_taken": ("T8",),
    "whatsapp_unknown_button": ("T10",),
    "stop_code_failed": ("T28",),
    "agent_stopped_by_code": ("T11",),
    # The agent's plans and the policy guard
    "policy_guard_rejected": ("T1", "T3", "T5"),
    "confirm_slot_not_offered": ("T3",),
    "plan_task_mismatch": ("T13",),
    "free_busy_task_mismatch": ("T13",),
    # Execution
    "execute_unknown_action": ("T3",),
    "execute_refused_no_valid_approval": ("T3", "T10"),
    "execute_refused_hash_mismatch": ("T3", "T10"),
    "execute_refused_recipient_not_in_thread": ("T5",),
    # Google
    "oauth_invalid_state": ("T16",),
    "oauth_exchange_failed": ("T16",),
    "google_account_mismatch": ("T16",),
    "google_token_rejected": ("E13",),
    # Volume
    "email_rate_limited": ("T24",),
}
UNLISTED = "unlisted"

SECURITY_EVENTS = metrics.create_counter("sa.security.events", "Security events, by kind (ADR-022)")


def prime() -> None:
    """Start every kind's counter at zero, once per process (metrics.configure calls it).

    Prometheus's increase() does not count a series' first sample. A counter created by the
    first event would show up already at 1, or at 6 after a burst, and a rule like "5 forged
    webhooks in 10 minutes" would see no increase at all. Found by firing a real attack at
    the cluster (deploy/k3d/test-detections.sh); the rule tests start their series at 0.
    """
    for kind in (*KINDS, UNLISTED):
        SECURITY_EVENTS.add(0, {"kind": kind})


def record(kind: str, user_id: UUID | None = None) -> None:
    """Count and log one security event. Ids only, never content (T22)."""
    label = kind if kind in KINDS else UNLISTED
    SECURITY_EVENTS.add(1, {"kind": label})
    logger.warning("security event: kind=%s user_id=%s", label, user_id or "-")
