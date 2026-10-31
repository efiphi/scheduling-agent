"""Run google-gateway locally:

    uv run --env-file deploy/compose/.env python -m google_gateway.serve

Why not plain `uvicorn ...`: uvicorn's access log prints every request URL, and the OAuth
callback URL contains the authorization code and state. With the access log off, the only
request logging is connection.py's, which records outcomes and user ids only (T16, T22).
"""

import os

import uvicorn

from google_gateway.app import create_app
from google_gateway.config import GatewayConfig
from google_gateway.wiring import connect_flow
from shared import log, tracing

# Local only by default. The container sets 0.0.0.0 and Compose publishes the port on
# 127.0.0.1, so the callback is still unreachable from the network.
HOST = os.environ.get("GATEWAY_BIND_HOST", "127.0.0.1")
PORT = 8001


def main() -> None:
    # JSON lines with the trace id; quiet HTTP clients and redaction (shared.log, T22).
    log.configure("google-gateway")
    tracing.configure("google-gateway")
    app = create_app(connect_flow(GatewayConfig.from_env()))
    uvicorn.run(app, host=HOST, port=PORT, access_log=False, server_header=False)


if __name__ == "__main__":
    main()
