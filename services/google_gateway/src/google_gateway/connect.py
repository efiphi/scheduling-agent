"""Start connecting a user's Google account; prints the consent URL to open in a browser.

    uv run --env-file deploy/compose/.env python -m google_gateway.connect --user-id <uuid>

A stand-in until web login exists (step 1.9): then the web app starts the same flow for the
logged-in user. Whoever runs this needs the gateway's secrets, which only the owner has.
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
