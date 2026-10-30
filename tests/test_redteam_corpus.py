"""The red-team corpus (redteam/attacks.json) is well formed and covers the injection threats."""

import json
from pathlib import Path

ATTACKS = Path(__file__).resolve().parents[1] / "redteam" / "attacks.json"


def test_corpus_is_well_formed() -> None:
    attacks = json.loads(ATTACKS.read_text())["attacks"]
    assert len({a["id"] for a in attacks}) == len(attacks) >= 10
    assert all(a["forbidden"] and a["body"] for a in attacks)


def test_corpus_covers_the_threat_model_injection_attacks() -> None:
    threats = {a["threat"] for a in json.loads(ATTACKS.read_text())["attacks"]}
    assert {"T1", "T2", "T3", "T4", "T5", "T6"} <= threats
