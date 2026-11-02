"""Every threat in the threat model has a test, an attack, or a written reason (ADR-020)."""

from redteam.coverage import TABLE, Row, reasons, render, rows, tests_by_threat, threats


def test_the_threat_model_is_read_in_full() -> None:
    # A change in the document's format must not quietly shrink the table to nothing.
    found = threats()
    assert {f"T{n}" for n in range(1, 32)} <= set(found)
    assert {f"E{n}" for n in range(1, 14)} <= set(found)


def test_every_threat_is_covered_or_explained() -> None:
    assert [row.threat for row in rows() if not row.covered] == []


def test_a_reason_is_dropped_once_a_threat_has_a_test_or_an_attack() -> None:
    assert [row.threat for row in rows() if row.reason and (row.tests or row.attacks)] == []


def test_a_reason_is_only_for_a_threat_that_exists() -> None:
    assert set(reasons()) <= set(threats())


def test_a_test_named_after_a_threat_points_at_a_real_one() -> None:
    assert set(tests_by_threat()) <= set(threats())


def test_the_committed_table_is_up_to_date() -> None:
    # If this fails: uv run python -m redteam.coverage
    assert TABLE.read_text(encoding="utf-8") == render(rows())


def test_a_threat_with_nothing_is_not_covered() -> None:
    assert not Row("T99", "x", 0, 0, "").covered
    assert Row("T99", "x", 1, 0, "").covered
    assert Row("T99", "x", 0, 1, "").covered
    assert Row("T99", "x", 0, 0, "reason").covered
