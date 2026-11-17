"""Write the api's OpenAPI schema, the source of the web app's TypeScript types.

    uv run python -m api.openapi > web/src/api/openapi.json
    (cd web && npm run api-types)

Built without a database, Redis or Google: the schema depends on the routes and models
only. A test fails if the committed file is out of date, so the web app's types always
match the server (docs/04-web-app.md).
"""

import json
from typing import Any, cast

from api.main import Deps, create_app


def schema() -> dict[str, Any]:
    unused: Any = None
    deps = Deps(
        login=cast(Any, unused),
        sessions=cast(Any, unused),
        store=cast(Any, unused),
        redis=cast(Any, unused),
        web_app_url="",
        cookie_secure=True,
    )
    return create_app(deps).openapi()


def main() -> None:
    print(json.dumps(schema(), indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
