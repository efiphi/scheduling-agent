"""Approving on WhatsApp (UC-W4, UC-W6): the same approval record, bound to the hash."""

from dataclasses import dataclass, field
from typing import cast
from uuid import UUID

import pytest
from api_fakes import HASH, FakeStore
from test_whatsapp import BACKUP, OWNER, FakeSender, FakeState

from api.whatsapp import APPROVED_REPLY, OWNER_REPLY, Inbound, Inbox, InboxState, Notifier


@dataclass
class Setup:
    inbox: Inbox
    notifier: Notifier
    store: FakeStore
    state: FakeState
    sender: FakeSender
    user: UUID
    handed: list[tuple[UUID, UUID]] = field(default_factory=list)


@pytest.fixture
def s() -> Setup:
    store, state, sender = FakeStore(), FakeState(), FakeSender()
    user = store.add_user()
    store.numbers[user] = OWNER
    store.backups[user] = [BACKUP]
    handed: list[tuple[UUID, UUID]] = []
    inbox = Inbox(
        store=store,
        state=cast(InboxState, state),
        sender=sender,
        hand_over=lambda u, a: handed.append((u, a)),
    )
    notifier = Notifier(
        store=store,
        state=cast(InboxState, state),
        inbox=inbox,
        sender=sender,
        template="action_waiting",
    )
    return Setup(inbox, notifier, store, state, sender, user, handed)


def press(s: Setup, button_id: str, sender: str = OWNER) -> str:
    return s.inbox.handle(Inbound(sender=sender, text="", message_id="m", button_id=button_id))


def test_uc_w4_any_message_shows_waiting_actions_with_buttons(s: Setup) -> None:
    action = s.store.add_action(s.user)
    assert s.inbox.handle(Inbound(OWNER, "היי", "m")) == "offered"
    [(to, text, buttons)] = s.sender.buttons
    assert to == OWNER and "dana@example.org" in text
    assert "מועדים פנויים:" in text and "יום " in text  # dates in Hebrew, not ISO
    assert "T0" not in text and "Asia/Jerusalem" not in text
    assert buttons == [(f"approve:{action}:{HASH}", "אשר"), (f"reject:{action}", "דחה")]


def test_nothing_waiting_says_so(s: Setup) -> None:
    s.inbox.handle(Inbound(OWNER, "היי", "m"))
    assert s.sender.sent == [(OWNER, OWNER_REPLY)]


def test_invariant_4_approve_button_records_a_whatsapp_approval_and_hands_it_over(s: Setup) -> None:
    action = s.store.add_action(s.user)
    assert press(s, f"approve:{action}:{HASH}") == "approved"
    assert s.store.channels[action] == "whatsapp"
    assert s.handed == [(s.user, action)]
    assert s.sender.sent[-1] == (OWNER, APPROVED_REPLY)


def test_t3_a_button_for_older_content_does_not_approve_the_new_content(s: Setup) -> None:
    action = s.store.add_action(s.user)
    assert press(s, f"approve:{action}:sha256:{'b' * 64}") == "approve_hash_mismatch"
    assert s.handed == [] and action not in s.store.approvals


def test_t10_pressing_approve_twice_approves_once(s: Setup) -> None:
    action = s.store.add_action(s.user)
    press(s, f"approve:{action}:{HASH}")
    assert press(s, f"approve:{action}:{HASH}") == "approve_not_pending"
    assert len(s.handed) == 1


def test_reject_button(s: Setup) -> None:
    action = s.store.add_action(s.user)
    assert press(s, f"reject:{action}") == "rejected"
    assert s.store.actions(s.user, "pending") == []


def test_t13_a_button_for_someone_elses_action_does_nothing(s: Setup) -> None:
    other = s.store.add_user("other@example.org")
    theirs = s.store.add_action(other)
    assert press(s, f"approve:{theirs}:{HASH}") == "approve_not_found"
    assert s.handed == []


def test_t8_a_backup_number_cannot_approve(s: Setup) -> None:
    action = s.store.add_action(s.user)
    assert press(s, f"approve:{action}:{HASH}", sender=BACKUP) == "backup_ignored"
    assert action not in s.store.approvals


@pytest.mark.parametrize("button", ["approve:not-a-uuid:x", "delete:everything", "approve:"])
def test_a_button_we_did_not_make_is_never_guessed(s: Setup, button: str) -> None:
    assert press(s, button) == "unknown_button"
    assert (s.user, "whatsapp_unknown_button") in s.store.events


def test_uc_w6_inside_the_window_the_action_arrives_with_buttons(s: Setup) -> None:
    action = s.store.add_action(s.user)
    s.state.open_window(s.user)
    assert s.notifier.notify(s.user, action) == "offered"
    assert len(s.sender.buttons) == 1 and s.sender.templates == []


def test_uc_w6_outside_the_window_only_the_template_goes_out(s: Setup) -> None:
    action = s.store.add_action(s.user)
    assert s.notifier.notify(s.user, action) == "template"
    assert s.sender.templates == [(OWNER, "action_waiting")] and s.sender.buttons == []


def test_no_verified_number_means_web_only(s: Setup) -> None:
    del s.store.numbers[s.user]
    assert s.notifier.notify(s.user, s.store.add_action(s.user)) == "no_whatsapp"


def test_an_action_already_decided_is_not_announced(s: Setup) -> None:
    action = s.store.add_action(s.user)
    s.store.reject(s.user, action)
    assert s.notifier.notify(s.user, action) == "not_pending"
