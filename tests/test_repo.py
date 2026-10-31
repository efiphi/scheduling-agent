"""Checks on the repository itself, for mistakes that only show up in a Docker build."""

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
