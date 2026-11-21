"""Application-level field encryption (DECISIONS D-019).

* ``encrypt``/``decrypt``: Fernet (AES-128-CBC + HMAC-SHA256) with a key list. New values are
  encrypted with the newest (first) key; any listed key can decrypt, which allows rotation.
* ``lookup_hash``: a deterministic HMAC-SHA256 for exact-match lookups and uniqueness checks
  without decrypting. It uses the oldest (last) key so hashes stay stable while new keys are
  prepended; retiring that key requires recomputing the hashes.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings


class DecryptionError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _fernet(keys: tuple[str, ...]) -> MultiFernet:
    if not keys:
        raise RuntimeError("FIELD_ENCRYPTION_KEYS is empty")
    return MultiFernet([Fernet(k.encode()) for k in keys])


def _keys() -> tuple[str, ...]:
    return tuple(settings.FIELD_ENCRYPTION_KEYS)


def encrypt(value: str) -> str:
    return _fernet(_keys()).encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet(_keys()).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError("Cannot decrypt field with the configured keys.") from exc


def lookup_hash(value: str) -> str:
    """Deterministic keyed hash for exact-match lookups. Case, spaces and punctuation are ignored,
    so "ET-123 456" and "et123456" are the same license."""
    key = _keys()[-1].encode()  # oldest key: stable across rotations until it is retired
    normalised = re.sub(r"[^0-9A-Za-z]", "", value).upper().encode()
    return hmac.new(key, normalised, hashlib.sha256).hexdigest()
