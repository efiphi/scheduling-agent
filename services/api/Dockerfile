# syntax=docker/dockerfile:1
# Image for the api service. Build from the repository root (the uv workspace):
#   docker build -f services/api/Dockerfile -t scheduling-agent-api .
#
# Base images are pinned by digest, not only by tag: a tag can be moved to different
# content, a digest cannot (T20).

# ---- Stage 1: install dependencies with uv -----------------------------------------
FROM python:3.13-slim@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962 AS build

COPY --from=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff /uv /bin/uv

# Compile bytecode at build time; copy files instead of linking from the uv cache.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Third-party dependencies first, from the lockfile only: this layer is reused
# as long as the dependencies do not change.
COPY pyproject.toml uv.lock ./
# Every workspace member's pyproject.toml is needed for uv to read the workspace, even the
# ones the api image does not install (e.g. packages/db). Only api and shared get installed.
COPY packages/db/pyproject.toml packages/db/
COPY packages/shared/pyproject.toml packages/shared/
COPY services/agent/pyproject.toml services/agent/
COPY services/api/pyproject.toml services/api/
COPY services/google_gateway/pyproject.toml services/google_gateway/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package api --no-install-workspace

# Then our own code. --no-editable installs it into the venv as a normal package,
# so the final image does not need the source tree.
COPY packages/shared packages/shared
COPY services/api services/api
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package api --no-editable

# ---- Stage 2: runtime -------------------------------------------------------------
# Only the virtual environment is copied over: no uv, no build cache, no source tree.
FROM python:3.13-slim@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962

# A dedicated unprivileged user with no login shell (T20, T21).
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY --from=build --chown=root:root /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

USER 10001:10001
EXPOSE 8000

# Docker asks this every 30s; slim has no curl, so use Python's standard library.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"]

# 0.0.0.0 inside the container; what is reachable from outside is decided by
# Compose / Kubernetes port mapping, not here.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
