"""Builds the real objects from configuration. Tests build them with fakes instead."""

from datetime import UTC, datetime
from uuid import UUID

from redis import Redis
from sqlalchemy import Engine

from db.engine import make_engine
from google_gateway.config import GatewayConfig
from google_gateway.connection import ConnectFlow
from google_gateway.coordination import RedisCoordination
from google_gateway.credentials_store import SqlCredentialRepository
from google_gateway.gmail import GmailReader, GoogleGmailReader
from google_gateway.google_oauth import FlowOAuthClient
from google_gateway.mail_store import SqlMailStore
from google_gateway.oauth_state import RedisStateStore
from google_gateway.poller import MailboxPoller
from google_gateway.token_crypto import EncryptedToken, TokenCipher


def gateway_engine(config: GatewayConfig) -> Engine:
    return make_engine(
        "gateway_service", config.db_password.get_secret_value(), config.db_host, config.db_port
    )


def google_client(config: GatewayConfig) -> FlowOAuthClient:
    return FlowOAuthClient(
        config.google_client_id, config.google_client_secret, config.redirect_uri
    )


def redis_client(config: GatewayConfig) -> Redis:
    return Redis(
        host=config.redis_host,
        port=config.redis_port,
        password=config.redis_password.get_secret_value(),
    )


def connect_flow(config: GatewayConfig) -> ConnectFlow:
    return ConnectFlow(
        states=RedisStateStore(redis_client(config)),
        google=google_client(config),
        repo=SqlCredentialRepository(gateway_engine(config)),
        cipher=TokenCipher.from_env(),
    )


def mailbox_poller(config: GatewayConfig) -> MailboxPoller:
    cipher = TokenCipher.from_env()
    google = google_client(config)

    def open_gmail(user_id: UUID, token: EncryptedToken) -> GmailReader:
        # Decrypted only here, in memory, for this poll (ADR-016).
        return GoogleGmailReader(google.credentials(cipher.decrypt(token, user_id)))

    return MailboxPoller(
        store=SqlMailStore(gateway_engine(config)),
        coordination=RedisCoordination(redis_client(config)),
        open_gmail=open_gmail,
        clock=lambda: datetime.now(UTC),
    )
