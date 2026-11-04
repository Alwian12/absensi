from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _derive_key(seed: str) -> bytes:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=None)
def _fernet_for(seed: str) -> Fernet:
    return Fernet(_derive_key(seed))


def _primary_seed() -> str:
    """Dedicated biometric key when configured (recommended, required in production).

    Falls back to the JWT secret only for backward compatibility so pre-existing
    deployments keep working (audit finding F-06).
    """
    return settings.face_encryption_key or settings.jwt_secret_key


def _candidate_seeds() -> list[str]:
    """Seeds to try when decrypting: primary first, then legacy JWT-derived key."""
    seeds = [_primary_seed()]
    legacy = settings.jwt_secret_key
    if legacy not in seeds:
        seeds.append(legacy)
    return seeds


def encrypt_text(plaintext: str) -> str:
    token = _fernet_for(_primary_seed()).encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_text(ciphertext: str) -> str:
    last_error: Exception | None = None
    for seed in _candidate_seeds():
        try:
            return _fernet_for(seed).decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            last_error = exc
    raise ValueError("Ciphertext embedding tidak valid") from last_error
