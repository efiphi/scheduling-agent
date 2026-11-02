"""Checks on the repository itself, for mistakes that only show up in a Docker build."""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MEMBERS = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]["workspace"]["members"]
DOCKERFILES = sorted([*ROOT.glob("services/*/Dockerfile"), *ROOT.glob("packages/*/Dockerfile")])


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.parent.name)
def test_every_dockerfile_copies_every_workspace_members_pyproject(dockerfile: Path) -> None:
    # uv reads the whole workspace even when it installs one package, so a member added to
    # pyproject.toml but missing here breaks that image's build (it happened in #14 and #21).
    text = dockerfile.read_text()
    missing = [m for m in MEMBERS if f"COPY {m}/pyproject.toml {m}/" not in text]
    assert missing == []


def test_there_are_dockerfiles_to_check() -> None:
    assert len(DOCKERFILES) >= 2


def test_redis_reads_outlast_every_queue_wait() -> None:
    # A consumer blocks up to BLOCK_MS for new messages; if the client's read timeout is not
    # longer, an idle queue raises TimeoutError and crashes the process (found 31.10).
    from agent import worker
    from api import notifier
    from google_gateway import executor, free_busy_responder, plan_handler
    from shared.streams import REDIS_SOCKET_TIMEOUT_SECONDS

    waits = [m.BLOCK_MS for m in (worker, notifier, executor, free_busy_responder, plan_handler)]
    assert 2 * max(waits) < REDIS_SOCKET_TIMEOUT_SECONDS * 1000


def test_every_process_logs_through_shared_log() -> None:
    # One JSON format with redaction everywhere (T22). A new entry point that calls
    # basicConfig would log in plain text, without redaction, and break the dashboards.
    sources = sorted(ROOT.glob("services/*/src/**/*.py")) + sorted(
        ROOT.glob("packages/*/src/**/*.py")
    )
    offenders = [
        str(p.relative_to(ROOT)) for p in sources if "logging.basicConfig" in p.read_text()
    ]
    assert offenders == []


def test_t22_metrics_carry_only_low_cardinality_attributes() -> None:
    # Metrics are counted across all users: a user id, an email address or a subject in an
    # attribute would leak personal data and create a series per value. Every recording in
    # the code is checked against shared.metrics.ALLOWED_ATTRIBUTES.
    import ast

    from shared.metrics import ALLOWED_ATTRIBUTES

    found: list[tuple[str, set[str]]] = []
    for path in sorted(ROOT.glob("services/*/src/**/*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("add", "record")
                and isinstance(node.func.value, ast.Attribute)
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "metrics"
            ):
                keys: set[str] = set()
                for arg in node.args[1:]:
                    assert isinstance(arg, ast.Dict), f"{path}: attributes must be a literal dict"
                    keys |= {str(k.value) for k in arg.keys if isinstance(k, ast.Constant)}
                found.append((f"{path.name}:{node.lineno}", keys))
    assert len(found) >= 8  # the recordings exist
    assert [(where, keys) for where, keys in found if not keys <= ALLOWED_ATTRIBUTES] == []


WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def test_t20_every_github_action_is_pinned_to_a_commit() -> None:
    # A tag can be moved to malicious code later; a commit hash cannot.
    assert WORKFLOWS
    for workflow in WORKFLOWS:
        for line in workflow.read_text().splitlines():
            action = re.match(r"\s*-?\s*uses:\s*([^\s#]+)", line)
            if action and not action[1].startswith("./"):
                assert re.search(r"@[0-9a-f]{40}$", action[1]), f"{workflow.name}: {action[1]}"


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_t20_every_base_image_is_pinned_by_digest(dockerfile: Path) -> None:
    for line in dockerfile.read_text().splitlines():
        base = re.match(r"FROM\s+(\S+)", line)
        if base:
            assert "@sha256:" in base[1], f"{dockerfile}: {line}"


def test_t20_every_image_a_workflow_runs_is_pinned_by_digest() -> None:
    # Images a workflow pulls and runs are named in an env value like ZAP_IMAGE.
    images = [
        (workflow.name, image)
        for workflow in WORKFLOWS
        for image in re.findall(r"_IMAGE:\s*(\S+)", workflow.read_text())
    ]
    assert images
    for name, image in images:
        assert "@sha256:" in image, f"{name}: {image}"


def test_every_zap_exception_gives_a_reason() -> None:
    # An exception with no reason is a finding someone silenced and nobody can review.
    for rules in sorted((ROOT / "deploy" / "zap").glob("*.tsv")):
        for line in rules.read_text().splitlines():
            if line and not line.startswith("#"):
                _rule, action, reason = line.split("\t")
                assert action == "IGNORE" and reason.startswith("(") and len(reason) > 10, line
