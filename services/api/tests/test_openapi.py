"""The web app's API types are generated from this schema; the committed copy must be current."""

import json
from pathlib import Path

from api.openapi import schema

COMMITTED = Path(__file__).resolve().parents[3] / "web" / "src" / "api" / "openapi.json"


def test_committed_openapi_schema_matches_the_code() -> None:
    # If this fails: uv run python -m api.openapi > web/src/api/openapi.json
    #                (cd web && npm run api-types)
    assert json.loads(COMMITTED.read_text()) == json.loads(json.dumps(schema()))
