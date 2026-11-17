"""rules.yml as Helm values for the Prometheus chart, so Argo CD deploys the same rules CI tests.

    python3 deploy/cluster/observability/detections/render.py

Writes prometheus-rules.yaml next to this file. tests/test_detections.py fails when it is out
of date. Standard library plus PyYAML (already a dev dependency).
"""

from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
RULES = HERE / "rules.yml"
VALUES = HERE / "prometheus-rules.yaml"

HEADER = (
    "# Generated from rules.yml by render.py. Do not edit by hand (ADR-022).\n"
    "# The Prometheus chart loads serverFiles.alerting_rules.yml as its alert rules.\n"
)


def render() -> str:
    rules = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    values = {"serverFiles": {"alerting_rules.yml": rules}}
    return HEADER + yaml.safe_dump(values, allow_unicode=True, sort_keys=False, width=120)


if __name__ == "__main__":
    VALUES.write_text(render(), encoding="utf-8")
