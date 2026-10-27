"""The rule filter (mail_filter.py) on synthetic emails, Hebrew and English (UC-M8, E9, T25)."""

import pytest
from mail_fakes import USER_EMAIL, meta

from google_gateway.gmail import MessageMeta
from google_gateway.mail_filter import Reason, classify


def decide(message: MessageMeta, tracked: bool = False) -> Reason:
    return classify(message, user_email=USER_EMAIL, tracked_thread=tracked).reason


@pytest.mark.parametrize(
    ("subject", "snippet"),
    [
        ("Can we schedule a call?", ""),
        ("Quick question", "Are you available on Tuesday for a short meeting?"),
        ("Re: project", "let's catch up next week"),
        ("אפשר לקבוע שיחה?", ""),
        ("שאלה קטנה", "מתי נוח לך להיפגש בשבוע הבא?"),
        ("בקשה", "אשמח לפגישה קצרה"),
        ("עדכון", "אתה זמין ביום שלישי?"),
        ("עדכון", "מה הזמינות שלך?"),
    ],
)
def test_scheduling_words_pass(subject: str, snippet: str) -> None:
    assert decide(meta(subject=subject, snippet=snippet)) is Reason.KEYWORD


@pytest.mark.parametrize(
    ("subject", "snippet"),
    [
        ("Invoice #1234", "Please find attached"),
        ("חשבונית לתשלום", "מצורפת החשבונית"),
        ("Recall of product", "a recall notice"),  # "call" inside a word is not a match
    ],
)
def test_unrelated_email_is_skipped_and_recorded(subject: str, snippet: str) -> None:
    decision = classify(
        meta(subject=subject, snippet=snippet), user_email=USER_EMAIL, tracked_thread=False
    )
    assert decision.reason is Reason.NO_MATCH
    assert not decision.passes
    assert decision.recorded_as_skipped


@pytest.mark.parametrize("subject", ["Invitation: Sync @ Tue 10:00", "הזמנה: פגישת צוות"])
def test_calendar_invitation_passes(subject: str) -> None:
    assert decide(meta(subject=subject)) is Reason.INVITATION


def test_reply_in_a_tracked_thread_passes_without_keywords() -> None:
    # UC-M2: the other side picks a slot. "Tuesday works" has no scheduling words.
    assert decide(meta(subject="Re: hello", snippet="Tuesday works"), tracked=True) is (
        Reason.TRACKED_THREAD
    )


@pytest.mark.parametrize(
    "headers",
    [
        {"Auto_Submitted": "auto-replied"},
        {"X_Autoreply": "yes"},
        {"Precedence": "auto_reply"},
    ],
)
def test_t25_auto_replies_are_skipped_even_in_a_tracked_thread(headers: dict[str, str]) -> None:
    # Answering an out-of-office reply that answers back is how agent loops start.
    assert decide(meta(subject="Out of office: meeting", extra=headers), tracked=True) is (
        Reason.AUTO_REPLY
    )


def test_auto_submitted_no_is_a_person() -> None:
    assert decide(meta(Auto_Submitted="no")) is Reason.KEYWORD


def test_t25_the_users_own_message_is_never_processed() -> None:
    decision = classify(
        meta(sender=f"Me <{USER_EMAIL.upper()}>"), user_email=USER_EMAIL, tracked_thread=True
    )
    assert decision.reason is Reason.OWN_MESSAGE
    assert not decision.recorded_as_skipped


@pytest.mark.parametrize(
    "message",
    [
        meta(subject="Webinar: schedule your demo", List_Unsubscribe="<mailto:u@example.org>"),
        meta(subject="Meeting notes digest", List_Id="<team.example.org>"),
        meta(subject="Book a call today!", labels=("INBOX", "CATEGORY_PROMOTIONS")),
        meta(subject="Weekly meeting digest", Precedence="bulk"),
    ],
)
def test_newsletters_with_scheduling_words_are_skipped(message: MessageMeta) -> None:
    assert decide(message) is Reason.BULK


@pytest.mark.parametrize(
    "sender", ["no-reply@example.org", "noreply@example.org", "alerts.donotreply@example.org"]
)
def test_no_reply_senders_are_skipped(sender: str) -> None:
    assert decide(meta(sender=sender, subject="Your meeting is confirmed")) is (
        Reason.NO_REPLY_SENDER
    )


@pytest.mark.parametrize("labels", [("SPAM",), ("INBOX", "SPAM"), ("DRAFT",), ("SENT",)])
def test_mail_outside_the_inbox_is_ignored_entirely(labels: tuple[str, ...]) -> None:
    decision = classify(meta(labels=labels), user_email=USER_EMAIL, tracked_thread=False)
    assert decision.reason is Reason.NOT_INBOX
    assert not decision.recorded_as_skipped
