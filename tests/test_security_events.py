"""Every security event the code writes is a known kind, tied to a threat (ADR-022)."""

import ast
from pathlib import Path

from redteam.coverage import threats
from shared.security import KINDS

ROOT = Path(__file__).resolve().parents[1]
WRITERS = {"security_event", "write_security_event", "record"}


def kinds_in_code() -> tuple[set[str], set[str]]:
    """The literal kinds passed to a writer, and the prefixes of kinds built with an f-string."""
    literals: set[str] = set()
    prefixes: set[str] = set()
    for path in sorted(ROOT.glob("services/*/src/**/*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute | ast.Name)):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            if name not in WRITERS:
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    literals.add(arg.value)
                elif isinstance(arg, ast.JoinedStr) and isinstance(arg.values[0], ast.Constant):
                    prefixes.add(str(arg.values[0].value))
    return literals, prefixes


def test_every_kind_the_code_writes_is_listed() -> None:
    literals, prefixes = kinds_in_code()
    assert len(literals) >= 15  # the scan finds the writers
    assert sorted(literals - set(KINDS)) == []
    for prefix in prefixes:
        assert any(kind.startswith(prefix) for kind in KINDS), prefix


def test_every_listed_kind_points_at_a_real_threat() -> None:
    known = set(threats())
    assert {kind: ids for kind, ids in KINDS.items() if not set(ids) <= known} == {}
