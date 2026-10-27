"""Run google-gateway locally:

    uv run --env-file deploy/compose/.env python -m google_gateway.serve

Why not plain `uvicorn ...`: uvicorn's access log prints every request URL, and the OAuth
callback URL contains the authorization code and state. With the access log off, the only
request logging is connection.py's, which records outcomes and user ids only (T16, T22).
"""

import logging

import uvicorn

from google_gateway.app import create_app
from google_gateway.config import GatewayConfig
from google_gateway.wiring import connect_flow

HOST = "127.0.0.1"  # local only until the gateway gets its container (step 1.5)
PORT = 8001


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = create_app(connect_flow(GatewayConfig.from_env()))
    uvicorn.run(app, host=HOST, port=PORT, access_log=False, server_header=False)


if __name__ == "__main__":
    main()
