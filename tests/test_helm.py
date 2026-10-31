"""Checks on the rendered Helm chart (deploy/helm/scheduling-agent): T13, T17, T21.

The security properties of the cluster live in YAML, so they are tested like code:
render the chart and check every pod. Needs the helm binary; skipped without it
(CI installs it in step 2.7).
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "deploy/helm/scheduling-agent"
HELM = shutil.which("helm")
needs_helm = pytest.mark.skipif(HELM is None, reason="helm is not installed")


def test_postgres_roles_script_is_the_same_file_compose_uses() -> None:
    # Two copies, because a Helm chart can only read files inside itself. One drifting
    # from the other would give the cluster different roles or GRANTs than Compose.
    compose = ROOT / "deploy/compose/postgres/init/01-roles.sh"
    assert (CHART / "files/01-roles.sh").read_bytes() == compose.read_bytes()


@pytest.fixture(scope="module")
def objects() -> list[dict[str, Any]]:
    assert HELM is not None
    out = subprocess.run(  # noqa: S603 - a fixed command, no user input
        [HELM, "template", "test", str(CHART)], capture_output=True, text=True, check=True
    ).stdout
    return [doc for doc in yaml.safe_load_all(out) if doc]


def pod_specs(objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    kinds = {"Deployment", "StatefulSet", "Job"}
    return {
        o["metadata"]["name"]: o["spec"]["template"]["spec"] for o in objects if o["kind"] in kinds
    }


@needs_helm
def test_t21_every_pod_is_hardened(objects: list[dict[str, Any]]) -> None:
    specs = pod_specs(objects)
    assert len(specs) >= 12  # nine workers, Postgres, Redis, migrations
    for name, spec in specs.items():
        assert spec["automountServiceAccountToken"] is False, name
        assert spec["enableServiceLinks"] is False, name
        assert spec["securityContext"]["runAsNonRoot"] is True, name
        assert spec["securityContext"]["runAsUser"] != 0, name
        assert spec["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}, name
        for container in spec["containers"]:
            sc = container["securityContext"]
            assert sc["allowPrivilegeEscalation"] is False, name
            assert sc["readOnlyRootFilesystem"] is True, name
            assert sc["capabilities"] == {"drop": ["ALL"]}, name


@needs_helm
def test_every_image_is_a_local_dev_tag_or_pinned_by_digest(objects: list[dict[str, Any]]) -> None:
    # T20: third-party images by digest. Our own move to immutable GHCR tags in step 2.5.
    for name, spec in pod_specs(objects).items():
        for container in spec["containers"]:
            image = container["image"]
            assert "@sha256:" in image or image.startswith("scheduling-agent-"), name


def secrets_of(spec: dict[str, Any]) -> set[str]:
    return {
        source["secretRef"]["name"]
        for container in spec["containers"]
        for source in container.get("envFrom", [])
        if "secretRef" in source
    }


@needs_helm
def test_t13_t17_each_component_reads_only_its_own_secret(objects: list[dict[str, Any]]) -> None:
    expected = {
        "api": {"api"},
        "whatsapp-webhook": {"api"},
        "notifier": {"api"},
        "google-gateway": {"gateway"},
        "gmail-poller": {"gateway"},
        "calendar-responder": {"gateway"},
        "plan-handler": {"gateway"},
        "action-executor": {"gateway"},
        "agent": {"agent"},
        "postgres": {"postgres"},
        "redis": {"redis"},
        "migrations-1": {"migrations"},
    }
    assert {name: secrets_of(spec) for name, spec in pod_specs(objects).items()} == expected


@needs_helm
def test_adr_011_the_agent_is_not_told_where_the_database_is(objects: list[dict[str, Any]]) -> None:
    agent = pod_specs(objects)["agent"]["containers"][0]
    assert "DB_HOST" not in {e["name"] for e in agent["env"]}


@needs_helm
def test_no_secret_values_in_the_chart(objects: list[dict[str, Any]]) -> None:
    # Secrets are created outside the chart (create-secrets.sh, Sealed Secrets in 2.3).
    assert [o for o in objects if o["kind"] == "Secret"] == []
