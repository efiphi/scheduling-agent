"""Encryption of Google refresh tokens (ADR-016). Tokens here are synthetic strings."""

import base64
import logging
from uuid import uuid4

import pytest

from google_gateway.token_crypto import (
    KEY_BYTES,
    EncryptedToken,
    TokenCipher,
    TokenCryptoError,
    new_key_entry,
    parse_keys,
)

TOKEN = "synthetic-refresh-token-for-tests"  # noqa: S105 - fake value, not a credential


def key(seed: int) -> bytes:
    return bytes([seed]) * KEY_BYTES


@pytest.fixture
def cipher() -> TokenCipher:
    return TokenCipher({1: key(1)})


def test_round_trip(cipher: TokenCipher) -> None:
    user = uuid4()
    assert cipher.decrypt(cipher.encrypt(TOKEN, user), user) == TOKEN


def test_t16_stored_bytes_do_not_contain_the_token(cipher: TokenCipher) -> None:
    stored = cipher.encrypt(TOKEN, uuid4())
    assert TOKEN.encode() not in stored.data


def test_same_token_encrypts_differently_each_time(cipher: TokenCipher) -> None:
    user = uuid4()
    assert cipher.encrypt(TOKEN, user).data != cipher.encrypt(TOKEN, user).data


def test_any_change_to_the_stored_bytes_fails(cipher: TokenCipher) -> None:
    user = uuid4()
    stored = cipher.encrypt(TOKEN, user)
    for position in (0, len(stored.data) // 2, len(stored.data) - 1):  # nonce, body, tag
        flipped = bytearray(stored.data)
        flipped[position] ^= 0x01
        with pytest.raises(TokenCryptoError):
            cipher.decrypt(EncryptedToken(bytes(flipped), stored.key_version), user)


def test_t16_token_moved_to_another_user_does_not_decrypt(cipher: TokenCipher) -> None:
    # Someone copies user A's encrypted token into user B's row (bug, or direct DB access).
    owner, other = uuid4(), uuid4()
    stored = cipher.encrypt(TOKEN, owner)
    with pytest.raises(TokenCryptoError):
        cipher.decrypt(stored, other)


def test_t16_wrong_key_does_not_decrypt() -> None:
    user = uuid4()
    stored = TokenCipher({1: key(1)}).encrypt(TOKEN, user)
    with pytest.raises(TokenCryptoError):
        TokenCipher({1: key(2)}).decrypt(stored, user)


def test_unknown_key_version_fails(cipher: TokenCipher) -> None:
    user = uuid4()
    stored = cipher.encrypt(TOKEN, user)
    with pytest.raises(TokenCryptoError):
        cipher.decrypt(EncryptedToken(stored.data, key_version=9), user)


def test_key_rotation_new_tokens_use_newest_key_old_tokens_still_read() -> None:
    user = uuid4()
    old = TokenCipher({1: key(1)}).encrypt(TOKEN, user)
    rotated = TokenCipher({1: key(1), 2: key(2)})
    assert rotated.encrypt(TOKEN, user).key_version == 2
    assert rotated.decrypt(old, user) == TOKEN


@pytest.mark.parametrize("bad", [{}, {1: b"short"}, {0: key(1)}])
def test_rejects_bad_key_configuration(bad: dict[int, bytes]) -> None:
    with pytest.raises(TokenCryptoError):
        TokenCipher(bad)


def test_t22_cipher_never_prints_its_keys(
    cipher: TokenCipher, caplog: pytest.LogCaptureFixture
) -> None:
    secret = key(1)
    logging.getLogger("test").warning("cipher state: %r", cipher)
    for text in (repr(cipher), str(cipher), caplog.text):
        assert base64.urlsafe_b64encode(secret).decode() not in text
        assert secret.hex() not in text


def test_t22_config_errors_do_not_echo_key_material() -> None:
    with pytest.raises(TokenCryptoError) as error:
        parse_keys("1:not*valid*base64*SECRETPART")
    assert "SECRETPART" not in str(error.value)


def test_new_key_entry_parses_back() -> None:
    entry = new_key_entry(3)
    keys = parse_keys(entry)
    assert list(keys) == [3]
    assert len(keys[3]) == KEY_BYTES


def test_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEYS", f"{new_key_entry(1)}, {new_key_entry(2)}")
    assert "current=2" in repr(TokenCipher.from_env())
