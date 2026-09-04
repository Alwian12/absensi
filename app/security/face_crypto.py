from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _derive_key(seed: str) -> bytes:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    seed = settings.face_encryption_key or settings.jwt_secret_key
    key = _derive_key(seed)
    return Fernet(key)


def encrypt_text(plaintext: str) -> str:
    token = _get_fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_text(ciphertext: str) -> str:
    try:
        plaintext = _get_fernet().decrypt(ciphertext.encode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("Ciphertext embedding tidak valid") from exc
    return plaintext.decode("utf-8")
