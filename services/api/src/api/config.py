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
    # WhatsApp (step 1b). Optional: without them the api runs without the webhook.
    whatsapp_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_app_secret: SecretStr | None = None
    whatsapp_verify_token: SecretStr | None = None
    # The approved utility template for notifications outside the 24-hour window.
    whatsapp_template: str | None = None

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
            whatsapp_token=_optional_secret("WHATSAPP_ACCESS_TOKEN"),
            whatsapp_phone_number_id=os.environ.get("WHATSAPP_PHONE_NUMBER_ID") or None,
            whatsapp_app_secret=_optional_secret("WHATSAPP_APP_SECRET"),
            whatsapp_verify_token=_optional_secret("WHATSAPP_VERIFY_TOKEN"),
            whatsapp_template=os.environ.get("WHATSAPP_NOTIFY_TEMPLATE") or None,
        )

    @property
    def whatsapp_configured(self) -> bool:
        return None not in (
            self.whatsapp_token,
            self.whatsapp_phone_number_id,
            self.whatsapp_app_secret,
            self.whatsapp_verify_token,
        )


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value or value == "change-me":
        raise ConfigError(f"{name} is not set (see deploy/compose/.env.example)")
    return value


def _optional_secret(name: str) -> SecretStr | None:
    value = os.environ.get(name, "")
    return SecretStr(value) if value and value != "change-me" else None
