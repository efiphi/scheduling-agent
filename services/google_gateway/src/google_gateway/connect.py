"""Start connecting a user's Google account; prints the consent URL to open in a browser.

    uv run --env-file deploy/compose/.env python -m google_gateway.connect --user-id <uuid>

The web app's "Connect Google" button starts the same flow through a one-time ticket
(shared/connect_ticket.py); this command is the owner's fallback. Whoever runs it needs the
gateway's secrets, which only the owner has. Afterwards the browser lands on the web app.
The URL works once, within 10 minutes, and only with the gateway running (serve.py).
"""

import argparse
import sys
from uuid import UUID

from google_gateway.config import GatewayConfig
from google_gateway.wiring import connect_flow


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="python -m google_gateway.connect")
    parser.add_argument("--user-id", type=UUID, required=True)
    args = parser.parse_args(argv)
    print(connect_flow(GatewayConfig.from_env()).start(args.user_id))


if __name__ == "__main__":
    main(sys.argv[1:])
