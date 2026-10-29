"""api configuration from the environment (deploy/compose/.env locally, Sealed Secrets later).

Secrets are SecretStr, so printing the config shows '**********' (T22). Error messages name
the missing variable, never a value.
"""

import os

from pydantic import SecretStr

from shared.schema import StrictModel

DEFAULT_REDIRECT_URI = "http://localhost:8000/auth/google/callback"
DEFAULT_WEB_APP_URL = "http://localhost:5173/"


class ConfigError(Exception):
    pass


class ApiConfig(StrictModel):
    google_client_id: str
    google_client_secret: SecretStr
    redirect_uri: str
    web_app_url: str
    db_password: SecretStr
    db_host: str
    db_port: int
    redis_password: SecretStr
    redis_host: str
    redis_port: int
    # Browsers treat http://localhost as a secure origin, so Secure cookies work locally too.
    cookie_secure: bool

    @classmethod
    def from_env(cls) -> "ApiConfig":
        return cls(
            google_client_id=_required("GOOGLE_LOGIN_CLIENT_ID"),
            google_client_secret=SecretStr(_required("GOOGLE_LOGIN_CLIENT_SECRET")),
            redirect_uri=os.environ.get("GOOGLE_LOGIN_REDIRECT_URI", DEFAULT_REDIRECT_URI),
            web_app_url=os.environ.get("WEB_APP_URL", DEFAULT_WEB_APP_URL),
            db_password=SecretStr(_required("API_DB_PASSWORD")),
            db_host=os.environ.get("DB_HOST", "127.0.0.1"),
            db_port=int(os.environ.get("DB_PORT", "5432")),
            redis_password=SecretStr(_required("REDIS_PASSWORD")),
            redis_host=os.environ.get("REDIS_HOST", "127.0.0.1"),
            redis_port=int(os.environ.get("REDIS_PORT", "6379")),
            cookie_secure=os.environ.get("SESSION_COOKIE_SECURE", "1") != "0",
        )


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value or value == "change-me":
        raise ConfigError(f"{name} is not set (see deploy/compose/.env.example)")
    return value
