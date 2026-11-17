"""Every PromQL query in the dashboards and alert rules, as a Prometheus rules file.

    python3 deploy/cluster/observability/promql_rules.py > promql.yaml
    promtool check rules promql.yaml

`promtool` checks syntax only for rules files, so each query becomes a recording rule.
CI runs this (the Kubernetes job): a typo in a query fails the build instead of leaving an
empty panel or an alert that never fires. LogQL and TraceQL have no such checker here.
Standard library plus PyYAML (already a dev dependency).
"""

import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent


def queries() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in sorted((HERE / "dashboards").glob("*.json")):
        for panel in json.loads(path.read_text())["panels"]:
            for target in panel["targets"]:
                if target["datasource"]["uid"] == "prometheus":
                    found.append((f"{path.stem}: {panel['title']}", target["expr"]))
    values = yaml.safe_load((HERE / "grafana.yaml").read_text())
    for group in values["alerting"]["rules.yaml"]["groups"]:
        for rule in group["rules"]:
            for query in rule["data"]:
                if query["datasourceUid"] == "prometheus":
                    found.append((f"alert: {rule['title']}", query["model"]["expr"]))
    return found


def rules_file() -> str:
    rules = [
        {"record": f"check:query_{i}", "expr": expr, "labels": {"source": where}}
        for i, (where, expr) in enumerate(queries())
    ]
    return yaml.safe_dump({"groups": [{"name": "dashboards-and-alerts", "rules": rules}]})


if __name__ == "__main__":
    sys.stdout.write(rules_file())
