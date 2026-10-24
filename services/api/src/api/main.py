"""FastAPI application for the api service.

Run locally:
    uv run --package api uvicorn api.main:app --host 127.0.0.1 --port 8000 --no-server-header

--no-server-header drops "server: uvicorn" from responses, so callers are not told
which server software and version to look up vulnerabilities for.
"""

from fastapi import FastAPI

from shared.schema import StrictModel

app = FastAPI(title="scheduling-agent api")


class Health(StrictModel):
    status: str


@app.get("/healthz")
def healthz() -> Health:
    """Liveness check for Docker and Kubernetes: the process is up and serving requests.

    Deliberately minimal: no version, hostname or dependency details, so an
    unauthenticated caller learns nothing about the deployment.
    """
    return Health(status="ok")
