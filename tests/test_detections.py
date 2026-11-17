"""The detection rules: deployed as tested, tied to a threat, each with a unit test (ADR-022)."""

import importlib.util
from pathlib import Path

import yaml

from redteam.coverage import threats

DETECTIONS = (
    Path(__file__).resolve().parents[1] / "deploy" / "cluster" / "observability" / "detections"
)
RULES = yaml.safe_load((DETECTIONS / "rules.yml").read_text(encoding="utf-8"))
TESTS = yaml.safe_load((DETECTIONS / "rules_test.yml").read_text(encoding="utf-8"))
ALERTS = [rule for group in RULES["groups"] for rule in group["rules"]]


def test_the_deployed_values_match_the_tested_rules() -> None:
    # If this fails: python3 deploy/cluster/observability/detections/render.py
    spec = importlib.util.spec_from_file_location("render", DETECTIONS / "render.py")
    assert spec and spec.loader
    render = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(render)
    assert (DETECTIONS / "prometheus-rules.yaml").read_text(encoding="utf-8") == render.render()


def test_every_rule_names_a_real_threat_a_severity_and_a_fixed_message() -> None:
    known = set(threats())
    for alert in ALERTS:
        assert alert["labels"]["threat"] in known, alert["alert"]
        assert alert["labels"]["severity"] in {"critical", "warning"}, alert["alert"]
        message = alert["annotations"]["summary_he"]
        # Fixed text only: a template could pull a value from an event into the message.
        assert message and "{{" not in message and "$" not in message, alert["alert"]


def test_every_rule_has_a_unit_test_that_makes_it_fire() -> None:
    fired = {
        case["alertname"]
        for test in TESTS["tests"]
        for case in test["alert_rule_test"]
        if case["exp_alerts"]
    }
    assert sorted({alert["alert"] for alert in ALERTS} - fired) == []
