"""Encryption of secrets stored in the database (workspace model API keys).

Values are encrypted with Fernet (AES-128-CBC with an HMAC-SHA256 tag, from the
`cryptography` package) under RAGNEX_ENCRYPTION_KEY, and stored as "enc:v1:<token>". The
tag means a wrong key or a tampered value is detected rather than decrypted into garbage.

Rotation: set the new key as RAGNEX_ENCRYPTION_KEY and list the old one in
RAGNEX_ENCRYPTION_PREVIOUS_KEYS, so existing values stay readable; then re-encrypt them
under the new key with `python -m backend.app.services.stored_secrets reencrypt`, after
which the old key can be dropped.
"""

from __future__ import annotations

import base64
import binascii

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

PREFIX = "enc:v1:"


class SecretUnavailable(RuntimeError):
    """A stored secret can't be decrypted with the configured keys."""


def normalize_key(value: str) -> bytes:
    """A Fernet key from 32 random bytes in base64, standard or URL-safe alphabet (so both
    `openssl rand -base64 32` and Fernet.generate_key() work). Raises ValueError."""
    raw = value.strip()
    try:
        decoded = base64.b64decode(raw.replace("-", "+").replace("_", "/"), validate=True)
    except (binascii.Error, ValueError):
        decoded = b""
    if len(decoded) != 32:
        raise ValueError(
            "must be 32 random bytes in base64 (generate one with: openssl rand -base64 32)"
        )
    return base64.urlsafe_b64encode(decoded)


def _fernet() -> MultiFernet:
    from backend.app.core.config import settings

    keys = [settings.ragnex_encryption_key, *settings.ragnex_encryption_previous_keys]
    return MultiFernet([Fernet(normalize_key(k)) for k in keys if k.strip()])


def is_encrypted(value: str | None) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt(plaintext: str) -> str:
    return PREFIX + _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(stored: str) -> str:
    """Plaintext of a stored value. Raises SecretUnavailable if no configured key opens it.
    A value without the prefix (stored before encryption existed) is returned as is."""
    if not is_encrypted(stored):
        return stored
    try:
        return _fernet().decrypt(stored[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise SecretUnavailable(
            "A stored API key can't be decrypted: RAGNEX_ENCRYPTION_KEY has changed since it "
            "was saved. A workspace owner needs to enter the key again in Settings, or the "
            "previous key must be listed in RAGNEX_ENCRYPTION_PREVIOUS_KEYS."
        ) from e


def reencrypt(stored: str) -> str:
    """The value encrypted under the current key (also encrypts an unencrypted value).
    Raises SecretUnavailable if it can't be read."""
    if not is_encrypted(stored):
        return encrypt(stored)
    try:
        return PREFIX + _fernet().rotate(stored[len(PREFIX):].encode("ascii")).decode("ascii")
    except InvalidToken as e:
        raise SecretUnavailable("A stored API key can't be decrypted with the configured keys.") from e
