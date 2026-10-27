"""Poll every connected mailbox once, or keep polling.

    uv run --env-file deploy/compose/.env python -m google_gateway.poll --once
    uv run --env-file deploy/compose/.env python -m google_gateway.poll --every 60

`--once` is what a Kubernetes CronJob will run each minute (Layer 2); `--every` is the
local stand-in. A per-user lock in Redis keeps overlapping runs from colliding.
"""

import argparse
import logging
import sys
import time

from google_gateway.config import GatewayConfig
from google_gateway.wiring import mailbox_poller

MIN_INTERVAL_SECONDS = 30


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="python -m google_gateway.poll")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--every", type=int, metavar="SECONDS")
    args = parser.parse_args(argv)
    if args.every is not None and args.every < MIN_INTERVAL_SECONDS:
        parser.error(f"--every must be at least {MIN_INTERVAL_SECONDS} seconds")

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # Google's HTTP client logs request URLs at INFO and below; keep it quiet (T22).
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)
    poller = mailbox_poller(GatewayConfig.from_env())
    while True:
        started = time.monotonic()
        poller.poll_all()
        if args.once:
            return
        time.sleep(max(0.0, args.every - (time.monotonic() - started)))


if __name__ == "__main__":
    main(sys.argv[1:])
