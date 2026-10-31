# syntax=docker/dockerfile:1
# Image for google-gateway: the OAuth callback server and the Gmail poller (one image,
# two commands in Compose). Build from the repository root (the uv workspace):
#   docker build -f services/google_gateway/Dockerfile -t scheduling-agent-gateway .
#
# Same hardening as the api image. Base images are pinned by digest (T20).

# ---- Stage 1: install dependencies with uv -----------------------------------------
FROM python:3.13-slim@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962 AS build

COPY --from=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Third-party dependencies first, from the lockfile only. uv needs every workspace
# member's pyproject.toml to read the workspace; only google-gateway, db and shared
# are installed (not the api).
COPY pyproject.toml uv.lock ./
COPY packages/db/pyproject.toml packages/db/
COPY packages/shared/pyproject.toml packages/shared/
COPY services/agent/pyproject.toml services/agent/
COPY services/api/pyproject.toml services/api/
COPY services/google_gateway/pyproject.toml services/google_gateway/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package google-gateway --no-install-workspace

# Then our own code, installed as normal packages (no source tree in the final image).
# Migrations are not copied: the gateway's database role cannot change the schema anyway.
COPY packages/shared packages/shared
COPY packages/db/src packages/db/src
COPY services/google_gateway services/google_gateway
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package google-gateway --no-editable

# ---- Stage 2: runtime -------------------------------------------------------------
FROM python:3.13-slim@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962

# A dedicated unprivileged user with no login shell (T20, T21).
# No pip at runtime: dependencies come from uv in the build stage, and pip's own vendored
# libraries (urllib3, msgpack, ...) were the only HIGH findings in Trivy's first scan.
RUN rm -rf /usr/local/lib/python3.13/site-packages/pip /usr/local/lib/python3.13/site-packages/pip-*.dist-info /usr/local/bin/pip*

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY --from=build --chown=root:root /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

USER 10001:10001
EXPOSE 8001

# Inside the container the server listens on every interface; Compose publishes the
# port on 127.0.0.1 only. The poller service overrides CMD and has no health check.
ENV GATEWAY_BIND_HOST=0.0.0.0
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/healthz', timeout=2).status == 200 else 1)"]

CMD ["python", "-m", "google_gateway.serve"]
