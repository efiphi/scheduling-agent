"""Print a new token encryption key entry for TOKEN_ENCRYPTION_KEYS.

    uv run --package google-gateway python -m google_gateway.keys          # version 1
    uv run --package google-gateway python -m google_gateway.keys 2        # for rotation

Paste the output into deploy/compose/.env (git-ignored). Never commit it.
"""

import sys

from google_gateway.token_crypto import new_key_entry


def main(argv: list[str]) -> None:
    version = int(argv[1]) if len(argv) > 1 else 1
    print(new_key_entry(version))


if __name__ == "__main__":
    main(sys.argv)
