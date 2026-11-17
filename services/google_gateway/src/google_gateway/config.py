"""google-gateway configuration, read from the environment.

Locally the values come from deploy/compose/.env (git-ignored) through
`uv run --env-file deploy/compose/.env ...`; in Kubernetes from a Sealed Secret (ADR-008).
Secrets are SecretStr, so printing the config shows '**********' instead of the value (T22).
Error messages name the missing variable, never a value.
"""

import os

from pydantic import SecretStr

from shared.schema import StrictModel

# Must match the redirect URI registered on the gateway-connect OAuth client (ADR-010).
DEFAULT_REDIRECT_URI = "http://localhost:8001/oauth/google/callback"


class ConfigError(Exception):
    pass


class GatewayConfig(StrictModel):
    google_client_id: str
    google_client_secret: SecretStr
    redirect_uri: str
    db_password: SecretStr
    db_host: str
    db_port: int
    redis_password: SecretStr
    redis_host: str
    redis_port: int

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        return cls(
            google_client_id=_required("GOOGLE_CONNECT_CLIENT_ID"),
            google_client_secret=SecretStr(_required("GOOGLE_CONNECT_CLIENT_SECRET")),
            redirect_uri=os.environ.get("GOOGLE_CONNECT_REDIRECT_URI", DEFAULT_REDIRECT_URI),
            db_password=SecretStr(_required("GATEWAY_DB_PASSWORD")),
            db_host=os.environ.get("DB_HOST", "127.0.0.1"),
            db_port=int(os.environ.get("DB_PORT", "5432")),
            redis_password=SecretStr(_required("REDIS_PASSWORD")),
            redis_host=os.environ.get("REDIS_HOST", "127.0.0.1"),
            redis_port=int(os.environ.get("REDIS_PORT", "6379")),
        )


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value or value == "change-me":
        raise ConfigError(f"{name} is not set (see deploy/compose/.env.example)")
    return value
