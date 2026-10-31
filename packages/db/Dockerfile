# syntax=docker/dockerfile:1
# Image for database migrations (Alembic), run once per release as a Kubernetes Job.
# Build from the repository root (the uv workspace):
#   docker build -f packages/db/Dockerfile -t scheduling-agent-migrations .
#
# The service images do not contain migrations: a service has no reason to change the
# schema, and its database role could not (ADR-005). Only this image runs as
# scheduling_owner, and only for as long as the migration takes.

# ---- Stage 1: install dependencies with uv -----------------------------------------
FROM python:3.13-slim@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962 AS build

COPY --from=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# uv needs every workspace member's pyproject.toml to read the workspace (tests/test_repo.py).
COPY pyproject.toml uv.lock ./
COPY packages/db/pyproject.toml packages/db/
COPY packages/shared/pyproject.toml packages/shared/
COPY services/agent/pyproject.toml services/agent/
COPY services/api/pyproject.toml services/api/
COPY services/google_gateway/pyproject.toml services/google_gateway/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package db --no-install-workspace

COPY packages/db/src packages/db/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package db --no-editable

# ---- Stage 2: runtime -------------------------------------------------------------
FROM python:3.13-slim@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962

# No pip at runtime: dependencies come from uv in the build stage, and pip's own vendored
# libraries (urllib3, msgpack, ...) were the only HIGH findings in Trivy's first scan.
RUN rm -rf /usr/local/lib/python3.13/site-packages/pip /usr/local/lib/python3.13/site-packages/pip-*.dist-info /usr/local/bin/pip*

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY --from=build --chown=root:root /app/.venv /app/.venv
COPY --chown=root:root packages/db/alembic.ini /migrations/alembic.ini
COPY --chown=root:root packages/db/migrations /migrations/migrations
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /migrations
USER 10001:10001

# Reads MIGRATION_DATABASE_URL (a scheduling_owner connection string) from the environment.
CMD ["alembic", "upgrade", "head"]
