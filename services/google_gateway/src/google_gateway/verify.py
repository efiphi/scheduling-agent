"""Prove a stored connection works: decrypt the token, refresh it, read from Gmail and Calendar.

    uv run --env-file deploy/compose/.env python -m google_gateway.verify --user-id <uuid>

Prints the mailbox address and counts only, never a token or any message content.
"""

import argparse
import sys
from uuid import UUID

from googleapiclient.discovery import build

from google_gateway.config import GatewayConfig
from google_gateway.credentials_store import SqlCredentialRepository
from google_gateway.token_crypto import TokenCipher
from google_gateway.wiring import gateway_engine, google_client


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="python -m google_gateway.verify")
    parser.add_argument("--user-id", type=UUID, required=True)
    args = parser.parse_args(argv)

    config = GatewayConfig.from_env()
    stored = SqlCredentialRepository(gateway_engine(config)).load_credentials(args.user_id)
    if stored is None:
        raise SystemExit("No connected Google account for this user.")
    encrypted, scopes = stored
    refresh_token = TokenCipher.from_env().decrypt(encrypted, args.user_id)
    credentials = google_client(config).credentials(refresh_token)

    gmail = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    profile = gmail.users().getProfile(userId="me").execute()
    calendar = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    events = calendar.events().list(calendarId="primary", maxResults=10).execute()

    print(f"scopes stored: {len(scopes)}")
    print(f"gmail: {profile['emailAddress']} ({profile['messagesTotal']} messages)")
    print(f"calendar: read {len(events.get('items', []))} event(s) from the primary calendar")


if __name__ == "__main__":
    main(sys.argv[1:])
