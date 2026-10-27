"""The rule filter (mail_filter.py) on synthetic emails, Hebrew and English (UC-M8, E9, T25)."""

import pytest
from mail_fakes import USER_EMAIL, meta

from google_gateway.gmail import MessageMeta
from google_gateway.mail_filter import Decision, Reason, classify


class BodyReader:
    def __init__(self, body: str) -> None:
        self.body = body
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return self.body


def decide(message: MessageMeta, body: str = "", tracked: bool = False) -> Decision:
    return classify(
        message, user_email=USER_EMAIL, tracked_thread=tracked, read_body=BodyReader(body)
    )


def reason(message: MessageMeta, body: str = "", tracked: bool = False) -> Reason:
    return decide(message, body, tracked).reason


@pytest.mark.parametrize(
    ("subject", "body"),
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
def test_scheduling_words_pass(subject: str, body: str) -> None:
    assert reason(meta(subject=subject), body) is Reason.KEYWORD


@pytest.mark.parametrize(
    "body",
    [
        "Thanks for the draft. When works for you to go over it?",
        "Do you have half an hour this week?",
        "Could we hop on for 15 minutes tomorrow?",
        "Let me know a good time to talk.",
        "תודה על הטיוטה. מתי נוח לך לעבור עליה?",
        "יש לך חצי שעה השבוע?",
        "אפשר לדבר על זה מחר?",
        "בוא נשב על זה ביום ראשון",
    ],
)
def test_requests_phrased_without_keywords_pass(body: str) -> None:
    assert reason(meta(subject="Re: Q3 budget"), body) is Reason.KEYWORD


def test_a_request_deep_inside_a_long_email_passes() -> None:
    # The request is in the third paragraph, far past Gmail's ~200-character snippet.
    body = (
        "היי,\n\n"
        + "עברתי על הדוח הרבעוני ששלחת. יש כמה נקודות בטבלת ההוצאות שלא ברורות לי. " * 4
        + "\n\nבנוסף, הנתונים של החודש האחרון נראים גבוהים מהרגיל, וכדאי לבדוק אותם.\n\n"
        + "אולי עדיף שנדבר על זה. מתי נוח לך השבוע?\n\nתודה"
    )
    assert body.index("מתי נוח") > 300
    assert reason(meta(subject="Re: דוח רבעוני"), body) is Reason.KEYWORD


def test_a_request_only_in_the_quoted_history_does_not_count() -> None:
    body = (
        "Thanks, the invoice is attached.\n\n"
        "On Tue, Oct 27, 2026 at 10:24 PM Dana Example <dana@example.org> wrote:\n"
        "> Can we schedule a meeting next week?\n"
    )
    assert reason(meta(subject="Re: invoice"), body) is Reason.NO_MATCH


def test_hebrew_gmail_reply_header_ends_the_new_part() -> None:
    body = (
        "מצורפת החשבונית.\n\n"
        "\u200fבתאריך יום ג׳, 27 באוק׳ 2026 ב-22:24 מאת Dana <dana@example.org>\u200f:\n"
        "> אפשר לקבוע פגישה?\n"
    )
    assert reason(meta(subject="Re: חשבונית"), body) is Reason.NO_MATCH


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        ("Invoice #1234", "Please find attached"),
        ("חשבונית לתשלום", "מצורפת החשבונית"),
        ("Recall of product", "a recall notice"),  # "call" inside a word is not a match
    ],
)
def test_unrelated_email_is_skipped_and_recorded(subject: str, body: str) -> None:
    decision = decide(meta(subject=subject), body)
    assert decision.reason is Reason.NO_MATCH
    assert not decision.passes
    assert decision.recorded_as_skipped


@pytest.mark.parametrize("subject", ["Invitation: Sync @ Tue 10:00", "הזמנה: פגישת צוות"])
def test_calendar_invitation_passes(subject: str) -> None:
    assert reason(meta(subject=subject)) is Reason.INVITATION


def test_reply_in_a_tracked_thread_passes_without_keywords() -> None:
    # UC-M2: the other side picks a slot. "Tuesday works" has no scheduling words.
    assert reason(meta(subject="Re: hello"), "Tuesday works", tracked=True) is (
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
    message = meta(subject="Out of office: meeting", extra=headers)
    assert reason(message, tracked=True) is Reason.AUTO_REPLY


def test_auto_submitted_no_is_a_person() -> None:
    assert reason(meta(Auto_Submitted="no")) is Reason.KEYWORD


def test_t25_the_users_own_message_is_never_processed() -> None:
    decision = decide(meta(sender=f"Me <{USER_EMAIL.upper()}>"), tracked=True)
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
    assert reason(message) is Reason.BULK


@pytest.mark.parametrize(
    "sender", ["no-reply@example.org", "noreply@example.org", "alerts.donotreply@example.org"]
)
def test_no_reply_senders_are_skipped(sender: str) -> None:
    assert reason(meta(sender=sender, subject="Your meeting is confirmed")) is (
        Reason.NO_REPLY_SENDER
    )


@pytest.mark.parametrize("labels", [("SPAM",), ("INBOX", "SPAM"), ("DRAFT",), ("SENT",)])
def test_mail_outside_the_inbox_is_ignored_entirely(labels: tuple[str, ...]) -> None:
    decision = decide(meta(labels=labels))
    assert decision.reason is Reason.NOT_INBOX
    assert not decision.recorded_as_skipped


@pytest.mark.parametrize(
    ("message", "tracked"),
    [
        (meta(labels=("SPAM",)), False),
        (meta(sender=USER_EMAIL), False),
        (meta(Auto_Submitted="auto-replied"), False),
        (meta(List_Id="<news.example.org>"), False),
        (meta(sender="noreply@example.org"), False),
        (meta(subject="Invitation: Sync"), False),
        (meta(subject="Re: hello"), True),
    ],
)
def test_bodies_are_opened_only_when_headers_cannot_decide(
    message: MessageMeta, tracked: bool
) -> None:
    body = BodyReader("Can we meet?")
    classify(message, user_email=USER_EMAIL, tracked_thread=tracked, read_body=body)
    assert body.calls == 0
