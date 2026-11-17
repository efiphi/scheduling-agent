"""GatewayConfig.from_env: required variables, and secrets that never print."""

import pytest

from google_gateway.config import ConfigError, GatewayConfig

SECRET = "synthetic-secret-value"  # noqa: S105 - fake value, not a credential

REQUIRED = {
    "GOOGLE_CONNECT_CLIENT_ID": "synthetic-client-id",
    "GOOGLE_CONNECT_CLIENT_SECRET": SECRET,
    "GATEWAY_DB_PASSWORD": SECRET,
    "REDIS_PASSWORD": SECRET,
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def test_reads_the_environment(env: pytest.MonkeyPatch) -> None:
    config = GatewayConfig.from_env()
    assert config.google_client_secret.get_secret_value() == SECRET
    assert config.redirect_uri == "http://localhost:8001/oauth/google/callback"


@pytest.mark.parametrize("name", sorted(REQUIRED))
@pytest.mark.parametrize("value", [None, "", "change-me"])
def test_missing_or_placeholder_values_fail(
    env: pytest.MonkeyPatch, name: str, value: str | None
) -> None:
    if value is None:
        env.delenv(name)
    else:
        env.setenv(name, value)
    with pytest.raises(ConfigError, match=name):
        GatewayConfig.from_env()


def test_t22_secrets_do_not_print(env: pytest.MonkeyPatch) -> None:
    config = GatewayConfig.from_env()
    assert SECRET not in repr(config)
    assert SECRET not in str(config)
    assert SECRET not in config.model_dump_json()
