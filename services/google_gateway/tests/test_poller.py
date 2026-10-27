"""The mailbox poller (poller.py) with fake Gmail, database and Redis."""

import logging
from dataclasses import dataclass
from uuid import UUID

import pytest
from google.auth.exceptions import RefreshError
from mail_fakes import NOW, USER_EMAIL, FakeCoordination, FakeGmail, FakeMailStore, meta

from google_gateway.poller import MailboxPoller
from google_gateway.token_crypto import EncryptedToken


@dataclass
class Setup:
    poller: MailboxPoller
    gmail: FakeGmail
    store: FakeMailStore
    coord: FakeCoordination
    user: UUID


@pytest.fixture
def s() -> Setup:
    gmail, store, coord = FakeGmail(), FakeMailStore(), FakeCoordination()
    user = store.add_user()

    def open_gmail(user_id: UUID, token: EncryptedToken) -> FakeGmail:
        return gmail

    poller = MailboxPoller(
        store=store, coordination=coord, open_gmail=open_gmail, clock=lambda: NOW
    )
    return Setup(poller, gmail, store, coord, user)


def test_meeting_request_reaches_the_agent_as_untrusted_data(s: Setup) -> None:
    s.gmail.add(meta("m1", cc="bob@example.org"), body="Is Tuesday 10:00 good?")
    assert s.poller.poll_user(s.user) == {"keyword": 1}

    [task] = s.coord.queue
    assert task.user_id == s.user
    assert task.email.sender == "dana@example.org"
    assert task.email.body_text == "Is Tuesday 10:00 good?"
    assert task.context.now == NOW
    thread_id, participants = s.store.threads[(s.user, "t-m1")]
    assert task.thread_id == thread_id
    # The user is not a participant: replies go to the others only (T5).
    assert participants == ["bob@example.org", "dana@example.org"]


def test_skipped_email_keeps_sender_and_subject_only(s: Setup) -> None:
    s.gmail.add(meta("m1", subject="Invoice #12"), body="secret body")
    assert s.poller.poll_user(s.user) == {"no_match": 1}
    assert s.coord.queue == []
    # The body was read to look for a request, then dropped: never stored.
    assert s.store.skipped == [(s.user, "dana@example.org", "Invoice #12")]
    assert "secret body" not in str(s.store)


def test_newsletter_body_is_never_fetched(s: Setup) -> None:
    s.gmail.add(meta("m1", subject="Book a call!", List_Id="<news.example.org>"))
    assert s.poller.poll_user(s.user) == {"bulk": 1}
    assert s.gmail.bodies_read == []


def test_body_is_fetched_once_for_filter_and_task(s: Setup) -> None:
    s.gmail.add(meta("m1", subject="Re: report"), body="When works for you?")
    assert s.poller.poll_user(s.user) == {"keyword": 1}
    assert s.gmail.bodies_read == ["m1"]
    assert s.coord.queue[0].email.body_text == "When works for you?"


def test_history_id_advances_after_the_batch(s: Setup) -> None:
    s.gmail.add(meta("m1"))
    s.gmail.add(meta("m2"))
    s.poller.poll_user(s.user)
    assert s.store.users[s.user].history_id == "102"


def test_first_poll_starts_from_now_and_ignores_the_old_inbox(s: Setup) -> None:
    user = s.store.add_user(history_id=None)
    s.gmail.add(meta("old"))
    assert s.poller.poll_user(user) == {}
    assert s.store.users[user].history_id == s.gmail.history_id
    assert s.coord.queue == []
    assert s.store.audits[-1][1] == "gmail_sync_started"


def test_e8_a_message_seen_twice_is_handled_once(s: Setup) -> None:
    s.gmail.add(meta("m1"))
    s.poller.poll_user(s.user)
    # The history id was not saved (say, a crash), so the same batch comes back.
    assert s.poller.poll_user(s.user) == {"duplicate": 1}
    assert len(s.coord.queue) == 1


def test_expired_history_resyncs_the_last_day_and_records_it(s: Setup) -> None:
    s.gmail.add(meta("m1"))
    s.gmail.expired = True
    assert s.poller.poll_user(s.user) == {"keyword": 1}
    assert s.store.audits[-1] == (s.user, "gmail_history_reset", {"messages": 1})
    assert s.store.users[s.user].history_id == s.gmail.history_id


def test_t24_rate_limit_keeps_the_flood_away_from_the_agent(s: Setup) -> None:
    s.coord.allow = 2
    for i in range(5):
        s.gmail.add(meta(f"m{i}"))
    assert s.poller.poll_user(s.user) == {"keyword": 2, "rate_limited": 3}
    assert len(s.coord.queue) == 2
    # Still visible to the user in the daily summary, and flagged.
    assert len(s.store.skipped) == 3
    assert (s.user, "email_rate_limited") in s.store.security_events


def test_e13_rejected_token_stops_polling_that_user(s: Setup) -> None:
    s.gmail.error = RefreshError("invalid_grant")  # type: ignore[no-untyped-call]
    assert s.poller.poll_user(s.user) == {"token_rejected": 1}
    assert s.user in s.store.expired
    assert s.user not in s.store.users_to_poll()


def test_a_locked_mailbox_is_left_to_the_poller_that_holds_it(s: Setup) -> None:
    s.gmail.add(meta("m1"))
    s.coord.locked.add(s.user)
    assert s.poller.poll_user(s.user) == {"locked": 1}
    assert s.coord.queue == []


def test_one_failing_mailbox_does_not_stop_the_others(s: Setup) -> None:
    other = s.store.add_user()
    broken = FakeGmail(error=RuntimeError("boom"))
    healthy = FakeGmail()
    healthy.add(meta("m1"))

    def open_gmail(user_id: UUID, token: EncryptedToken) -> FakeGmail:
        return broken if user_id == s.user else healthy

    poller = MailboxPoller(
        store=s.store, coordination=s.coord, open_gmail=open_gmail, clock=lambda: NOW
    )
    poller.poll_all()
    assert [t.user_id for t in s.coord.queue] == [other]


def test_sender_without_a_usable_address_is_kept_visible_not_guessed(s: Setup) -> None:
    s.gmail.add(meta("m1", sender="Calendar bot <not-an-address>"))
    assert s.poller.poll_user(s.user) == {"invalid_message": 1}
    assert s.coord.queue == []
    assert len(s.store.skipped) == 1


def test_t22_logs_hold_counts_not_content(s: Setup, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    s.gmail.add(meta("m1", subject="Secret project meeting"), body="confidential details")
    s.poller.poll_user(s.user)
    assert "keyword" in caplog.text
    for content in ("Secret project", "confidential", "dana@example.org", USER_EMAIL):
        assert content not in caplog.text
