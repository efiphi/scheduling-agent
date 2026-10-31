"""Poll every connected mailbox once, or keep polling.

    uv run --env-file deploy/compose/.env python -m google_gateway.poll --once
    uv run --env-file deploy/compose/.env python -m google_gateway.poll --every 60

`--once` is what the Kubernetes CronJob runs each minute (gmail-poll); `--every` is the
Compose stand-in. A per-user lock in Redis keeps overlapping runs from colliding.
"""

import argparse
import sys
import time

from google_gateway.config import GatewayConfig
from google_gateway.wiring import mailbox_poller
from shared import log, tracing

MIN_INTERVAL_SECONDS = 30


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="python -m google_gateway.poll")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--every", type=int, metavar="SECONDS")
    args = parser.parse_args(argv)
    if args.every is not None and args.every < MIN_INTERVAL_SECONDS:
        parser.error(f"--every must be at least {MIN_INTERVAL_SECONDS} seconds")

    # JSON lines with the trace id; quiet HTTP clients and redaction (shared.log, T22).
    log.configure("gmail-poll")
    tracing.configure("gmail-poll")
    poller = mailbox_poller(GatewayConfig.from_env())
    while True:
        started = time.monotonic()
        poller.poll_all()
        if args.once:
            return
        time.sleep(max(0.0, args.every - (time.monotonic() - started)))


if __name__ == "__main__":
    main(sys.argv[1:])
