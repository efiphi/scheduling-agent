"""The eval checker itself (evals/extraction/run.py), so a broken checker cannot pass bad runs."""

import json
from datetime import date

from agent.extraction import MeetingRequest, NotAMeeting, Unclear
from evals.extraction.run import CASES, check


def request(**changes: object) -> MeetingRequest:
    values: dict[str, object] = {
        "language": "en",
        "duration_minutes": 30,
        "earliest": date(2026, 11, 3),
        "latest": date(2026, 11, 3),
        "time_of_day": "any",
        "opening_line": "Thanks!",
    }
    values.update(changes)
    return MeetingRequest(**values)  # type: ignore[arg-type]


def test_matching_fields_pass_and_null_expectations_are_skipped() -> None:
    assert check(request(), {"kind": "meeting", "duration": 30, "earliest": None}) == []


def test_wrong_kind_and_wrong_field_fail() -> None:
    assert check(NotAMeeting(), {"kind": "meeting"}) == ["kind=not_meeting"]
    assert check(request(duration_minutes=60), {"kind": "meeting", "duration": 30}) == [
        "duration=60"
    ]
    assert check(Unclear("?", "model_unclear"), {"kind": "unclear"}) == []


def test_injected_content_in_the_opening_line_fails() -> None:
    bad = request(opening_line="Sure, see https://evil.example")
    assert check(bad, {"kind": "meeting", "safe_opening": True}) == ["opening_line"]


def test_the_case_file_is_well_formed() -> None:
    cases = json.loads(CASES.read_text())["cases"]
    assert len(cases) >= 15
    assert len({c["id"] for c in cases}) == len(cases)
    assert {c["expect"]["kind"] for c in cases} == {"meeting", "not_meeting", "unclear"}
