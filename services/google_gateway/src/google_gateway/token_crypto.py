"""Encryption of Google refresh tokens at rest (ADR-016, T16).

AES-256-GCM: authenticated encryption, so any change to the stored bytes makes decryption
fail instead of returning garbage. Each encryption uses a fresh random 96-bit nonce.

The token is bound to its user: the user id is authenticated "associated data". Moving
one user's encrypted token into another user's row makes decryption fail (T13, T16).

Keys never live in the database. They come from the TOKEN_ENCRYPTION_KEYS environment
variable as versioned entries ("1:<base64>,2:<base64>"); new tokens use the highest
version, and old tokens stay readable until re-encrypted, so a key can be rotated.
"""

import base64
import binascii
import os
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32  # AES-256
NONCE_BYTES = 12  # 96-bit, the GCM standard
# Domain separation: a ciphertext made for this purpose cannot pass as one made for another.
_AAD_PREFIX = b"scheduling-agent/google-refresh-token/v1/"


class TokenCryptoError(Exception):
    """Raised for any decryption or configuration failure, without revealing which part failed."""


@dataclass(frozen=True)
class EncryptedToken:
    """What is stored in google_credentials: nonce + ciphertext + tag, and the key version."""

    data: bytes
    key_version: int


class TokenCipher:
    def __init__(self, keys: Mapping[int, bytes]) -> None:
        if not keys:
            raise TokenCryptoError("no token encryption keys configured")
        for version, key in keys.items():
            if version < 1 or len(key) != KEY_BYTES:
                raise TokenCryptoError("each key needs a positive version and 32 bytes")
        self._keys = dict(keys)
        self._current = max(keys)

    @classmethod
    def from_env(cls, variable: str = "TOKEN_ENCRYPTION_KEYS") -> "TokenCipher":
        value = os.environ.get(variable, "")
        return cls(parse_keys(value))

    def __repr__(self) -> str:
        # Never print key material, even in a debugger or a traceback (T22).
        return f"TokenCipher(versions={sorted(self._keys)}, current={self._current})"

    def encrypt(self, token: str, user_id: UUID) -> EncryptedToken:
        nonce = os.urandom(NONCE_BYTES)
        sealed = AESGCM(self._keys[self._current]).encrypt(
            nonce, token.encode(), _associated_data(user_id)
        )
        return EncryptedToken(data=nonce + sealed, key_version=self._current)

    def decrypt(self, encrypted: EncryptedToken, user_id: UUID) -> str:
        key = self._keys.get(encrypted.key_version)
        if key is None or len(encrypted.data) <= NONCE_BYTES:
            raise TokenCryptoError("cannot decrypt token")
        nonce, sealed = encrypted.data[:NONCE_BYTES], encrypted.data[NONCE_BYTES:]
        try:
            plain = AESGCM(key).decrypt(nonce, sealed, _associated_data(user_id))
        except InvalidTag:
            raise TokenCryptoError("cannot decrypt token") from None
        return plain.decode()


def _associated_data(user_id: UUID) -> bytes:
    return _AAD_PREFIX + user_id.bytes


def parse_keys(value: str) -> dict[int, bytes]:
    """Parse "1:<base64>,2:<base64>". Errors never echo the key material."""
    keys: dict[int, bytes] = {}
    for entry in filter(None, (part.strip() for part in value.split(","))):
        version_text, sep, encoded = entry.partition(":")
        if not sep or not version_text.isdigit():
            raise TokenCryptoError("TOKEN_ENCRYPTION_KEYS entries look like '1:<base64>'")
        try:
            # validate=True: urlsafe_b64decode would silently skip invalid characters and
            # turn a corrupted key into a different one.
            keys[int(version_text)] = base64.b64decode(encoded, altchars=b"-_", validate=True)
        except (binascii.Error, ValueError):
            raise TokenCryptoError(f"key version {version_text} is not valid base64") from None
    return keys


def new_key_entry(version: int) -> str:
    """A fresh random key, formatted for TOKEN_ENCRYPTION_KEYS."""
    return f"{version}:{base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode()}"
