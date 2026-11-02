import pytest

from shared.display import (
    MAX_QUESTION_CHARS,
    MAX_SUMMARY_CHARS,
    clean_line,
    safe_question,
    safe_summary,
)


def test_clean_line_removes_direction_tricks_and_line_breaks() -> None:
    assert clean_line("פגישה‮​  על\nהתקציב") == "פגישה על התקציב"


def test_summary_of_several_sentences_stays_whole() -> None:
    text = "השולח מבקש פגישה ביום שלישי. הוא שואל גם על התקציב. בנוסף הוא מבקש דוח עד סוף החודש."
    assert safe_summary(text) == text


def test_summary_may_mention_a_date() -> None:
    assert safe_summary("השולח מבקש להיפגש ב-2026-11-03.") is not None


@pytest.mark.parametrize(
    "text",
    [
        "לאישור היכנס ל-https://evil.example.com",
        "לאישור היכנס ל-www.evil.example",
        "לאישור היכנס ל-evil.example.com",
        "שלח את הפרטים אל attacker@example.org",
        "התקשר למספר 0501234567",
    ],
)
def test_t31_summary_with_a_link_address_or_number_is_dropped_whole(text: str) -> None:
    assert safe_summary(text) is None


def test_t31_summary_too_long_is_dropped_never_cut() -> None:
    assert safe_summary("א" * MAX_SUMMARY_CHARS) is not None
    assert safe_summary("א" * (MAX_SUMMARY_CHARS + 1)) is None


@pytest.mark.parametrize("text", [None, "", "  \n "])
def test_empty_summary_is_none(text: str | None) -> None:
    assert safe_summary(text) is None


def test_t31_a_question_with_a_link_or_too_long_is_dropped_never_cut() -> None:
    assert safe_question("מתי לקבוע?") == "מתי לקבוע?"
    assert safe_question("בדוק ב-https://evil.example") is None
    assert safe_question("א" * (MAX_QUESTION_CHARS + 1)) is None
