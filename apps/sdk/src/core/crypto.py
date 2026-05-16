"""Field-level secret encryption helpers.

This module provides authenticated encryption for sensitive values that must be
stored and later decrypted for outbound OAuth/API calls.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Final

from src.core.config import settings

ENCRYPTED_SECRET_PREFIX: Final[str] = "enc:v1:"
_NONCE_BYTES: Final[int] = 16
_TAG_BYTES: Final[int] = 32


def _master_key() -> bytes:
    """Return a stable master key derived from configured secret material."""
    key_material = settings.TOKEN_ENCRYPTION_KEY or settings.JWT_SECRET
    return hashlib.sha256(key_material.encode("utf-8")).digest()


def _derive_subkeys(master_key: bytes) -> tuple[bytes, bytes]:
    """Derive distinct encryption and MAC keys from the master key."""
    encryption_key = hmac.new(master_key, b"enc", hashlib.sha256).digest()
    mac_key = hmac.new(master_key, b"mac", hashlib.sha256).digest()
    return encryption_key, mac_key


def _keystream(encryption_key: bytes, nonce: bytes, length: int) -> bytes:
    """Generate a pseudorandom keystream with HMAC-SHA256 blocks."""
    stream = bytearray()
    counter = 0
    while len(stream) < length:
        block = hmac.new(
            encryption_key,
            nonce + counter.to_bytes(4, byteorder="big", signed=False),
            hashlib.sha256,
        ).digest()
        stream.extend(block)
        counter += 1
    return bytes(stream[:length])


def is_encrypted_secret(value: str) -> bool:
    """Return whether a value is stored in encrypted format."""
    return value.startswith(ENCRYPTED_SECRET_PREFIX)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt plaintext for persistent storage.

    Existing encrypted values are returned unchanged.
    """
    if is_encrypted_secret(plaintext):
        return plaintext

    plaintext_bytes = plaintext.encode("utf-8")
    nonce = secrets.token_bytes(_NONCE_BYTES)
    encryption_key, mac_key = _derive_subkeys(_master_key())
    stream = _keystream(encryption_key, nonce, len(plaintext_bytes))
    ciphertext = bytes(p ^ s for p, s in zip(plaintext_bytes, stream))
    tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(nonce + tag + ciphertext).decode("ascii")
    return f"{ENCRYPTED_SECRET_PREFIX}{encoded}"


def decrypt_secret(value: str) -> str:
    """Decrypt a stored secret.

    Legacy plaintext values are returned as-is so older rows remain readable.
    """
    if not is_encrypted_secret(value):
        return value

    encoded = value[len(ENCRYPTED_SECRET_PREFIX) :]
    raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
    if len(raw) < _NONCE_BYTES + _TAG_BYTES:
        raise ValueError("Encrypted secret payload is too short")

    nonce = raw[:_NONCE_BYTES]
    tag = raw[_NONCE_BYTES : _NONCE_BYTES + _TAG_BYTES]
    ciphertext = raw[_NONCE_BYTES + _TAG_BYTES :]

    encryption_key, mac_key = _derive_subkeys(_master_key())
    expected_tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected_tag):
        raise ValueError("Encrypted secret integrity check failed")

    stream = _keystream(encryption_key, nonce, len(ciphertext))
    plaintext_bytes = bytes(c ^ s for c, s in zip(ciphertext, stream))
    return plaintext_bytes.decode("utf-8")
