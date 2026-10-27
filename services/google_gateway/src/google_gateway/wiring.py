"""Builds the real objects from configuration. Tests build ConnectFlow with fakes instead."""

from redis import Redis
from sqlalchemy import Engine

from db.engine import make_engine
from google_gateway.config import GatewayConfig
from google_gateway.connection import ConnectFlow
from google_gateway.credentials_store import SqlCredentialRepository
from google_gateway.google_oauth import FlowOAuthClient
from google_gateway.oauth_state import RedisStateStore
from google_gateway.token_crypto import TokenCipher


def gateway_engine(config: GatewayConfig) -> Engine:
    return make_engine(
        "gateway_service", config.db_password.get_secret_value(), config.db_host, config.db_port
    )


def google_client(config: GatewayConfig) -> FlowOAuthClient:
    return FlowOAuthClient(
        config.google_client_id, config.google_client_secret, config.redirect_uri
    )


def connect_flow(config: GatewayConfig) -> ConnectFlow:
    redis = Redis(
        host=config.redis_host,
        port=config.redis_port,
        password=config.redis_password.get_secret_value(),
    )
    return ConnectFlow(
        states=RedisStateStore(redis),
        google=google_client(config),
        repo=SqlCredentialRepository(gateway_engine(config)),
        cipher=TokenCipher.from_env(),
    )
