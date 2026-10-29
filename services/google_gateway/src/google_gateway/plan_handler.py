"""Turning the agent's plans into pending actions or questions (step 1.8).

    python -m google_gateway.plan_handler

For each AgentPlan on the plans stream:
1. It must answer a task this gateway issued, for the same user and thread (T13). A plan
   for anything else is a security event and is dropped.
2. not_a_meeting_request: the thread is closed (it stays in the audit log).
3. ask_user: a question is recorded for the user (UC-M7).
4. propose_slots: the calendar is read again, the policy guard checks the plan
   (policy_guard.py), the email is built from the template, and a pending action is
   created with its content hash and expiry. Nothing is sent: that needs an approval.
A plan delivered twice creates nothing new (unique task id, E8). Logs: ids and outcomes.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from google.auth.exceptions import RefreshError
from pydantic import ValidationError
from redis import Redis
from redis.exceptions import ResponseError

from google_gateway.actions_store import ActionStore
from google_gateway.calendar import busy_intervals
from google_gateway.coordination import PollCoordination
from google_gateway.email_template import build_reply
from google_gateway.free_busy_responder import OpenCalendar
from google_gateway.mail_store import MailStore
from google_gateway.pending_action import content_hash, expires_at, reply_payload
from google_gateway.policy_guard import GuardInput, check_reply
from google_gateway.token_crypto import EncryptedToken
from shared.messages import AgentPlan, Interval, ProposeSlots
from shared.streams import AGENT_PLANS

logger = logging.getLogger(__name__)

GROUP = "gateway"
BLOCK_MS = 5_000
GUARD_REJECTED_QUESTION = (
    "הסוכן הציע תשובה שלא עברה את בדיקות הבטיחות, ולכן היא לא הוצגה. כדאי להסתכל על המייל בעצמך."
)
CALENDAR_UNAVAILABLE_QUESTION = "לא הצלחתי לבדוק שוב את היומן לפני ההצעה. כדאי לענות בעצמך."


@dataclass(frozen=True)
class PlanHandler:
    actions: ActionStore
    mail: MailStore
    coordination: PollCoordination
    open_calendar: OpenCalendar
    clock: Callable[[], datetime]

    def handle(self, plan: AgentPlan) -> str:
        record = self.coordination.task_record(plan.task_id)
        if record is None or (record.user_id, record.thread_id) != (plan.user_id, plan.thread_id):
            # Not a task we issued, or pointed at another user or thread: drop it (T13).
            self.mail.security_event(plan.user_id, "plan_task_mismatch", {})
            return "rejected_unknown_task"

        decision = plan.decision
        if decision.kind == "not_a_meeting_request":
            self.actions.close_thread(plan.user_id, plan.thread_id, "not_a_meeting_request")
            return "closed"
        if decision.kind == "ask_user":
            created = self.actions.create_question(
                plan.user_id, plan.thread_id, plan.task_id, decision.question
            )
            return "question" if created else "duplicate"
        return self._propose(plan, decision, record.subject)

    def _propose(self, plan: AgentPlan, decision: ProposeSlots, subject: str) -> str:
        user, thread_id = plan.user_id, plan.thread_id
        mailbox = self.mail.mailbox(user)
        thread = self.actions.thread(user, thread_id)
        if mailbox is None or thread is None:
            return "rejected_not_connected"
        now = self.clock()
        context = self.mail.agent_context(user, now)

        busy = self._busy_now(user, mailbox.token, context.time_zone, decision.slots)
        if busy is None:
            self.actions.create_question(
                user, thread_id, plan.task_id, CALENDAR_UNAVAILABLE_QUESTION
            )
            return "question"

        result = check_reply(
            GuardInput(
                decision=decision,
                context=context,
                user_email=mailbox.email,
                participants=thread.participants,
                busy_now=busy,
                replies_sent_in_thread=self.actions.replies_sent_in_thread(user, thread_id),
                actions_today=self.actions.actions_since(user, now - timedelta(days=1)),
            )
        )
        if not result.allowed:
            # Reason codes only; the user is told to look at the email themselves.
            self.mail.security_event(
                user, "policy_guard_rejected", {"violations": list(result.violations)}
            )
            self.actions.create_question(user, thread_id, plan.task_id, GUARD_REJECTED_QUESTION)
            return "rejected_by_guard"

        email = build_reply(
            language=decision.language,
            opening_line=decision.opening_line,
            slots=decision.slots,
            duration_minutes=decision.duration_minutes,
            time_zone=context.time_zone,
            incoming_subject=subject,
        )
        payload = reply_payload(
            decision=decision,
            email=email,
            recipients=result.recipients,
            gmail_thread_id=thread.gmail_thread_id,
            time_zone=context.time_zone,
        )
        action_id = self.actions.create_reply_action(
            user,
            thread_id,
            plan.task_id,
            payload,
            content_hash(payload),
            expires_at(context, self.actions.end_of_workday(user)),
        )
        return "pending_action" if action_id else "duplicate"

    def _busy_now(
        self, user: UUID, token: EncryptedToken, time_zone: str, slots: tuple[Interval, ...]
    ) -> tuple[Interval, ...] | None:
        """Busy times over the proposed slots, read now (E1). None if the calendar failed."""
        window = Interval(start=min(s.start for s in slots), end=max(s.end for s in slots))
        try:
            events = self.open_calendar(user, token, time_zone).events(window)
        except RefreshError:
            self.mail.mark_expired(user)
            return None
        except Exception as exc:
            logger.error("calendar re-check failed: error=%s", type(exc).__name__)
            return None
        return busy_intervals(events, window)


def run_once(redis: Redis, handler: PlanHandler, consumer: str) -> int:
    response: Any = redis.xreadgroup(GROUP, consumer, {AGENT_PLANS: ">"}, count=1, block=BLOCK_MS)
    if not response:
        return 0
    message_id, fields = response[0][1][0]
    try:
        plan = AgentPlan.model_validate_json(fields.get(b"plan", b""))
    except ValidationError:
        logger.error("invalid plan dropped")
    else:
        outcome = handler.handle(plan)
        logger.info("plan handled: task_id=%s outcome=%s", plan.task_id, outcome)
    redis.xack(AGENT_PLANS, GROUP, message_id)
    return 1


def ensure_group(redis: Redis) -> None:
    try:
        redis.xgroup_create(AGENT_PLANS, GROUP, id="0", mkstream=True)
    except ResponseError as error:
        if "BUSYGROUP" not in str(error):
            raise


def main() -> None:
    import socket

    from google_gateway.config import GatewayConfig
    from google_gateway.wiring import plan_handler, redis_client

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)  # T22
    config = GatewayConfig.from_env()
    redis, handler = redis_client(config), plan_handler(config)
    ensure_group(redis)
    while True:
        run_once(redis, handler, socket.gethostname())


if __name__ == "__main__":
    main()
