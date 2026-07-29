import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from app.config import settings


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _base64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_token(subject: str, role: str) -> str:
    header = {"alg": settings.jwt_algorithm, "typ": "JWT"}
    now = int(time.time())
    payload = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": now + settings.jwt_expire_minutes * 60,
    }
    header_segment = _base64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_segment = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_segment}.{payload_segment}".encode()
    signature = hmac.new(settings.jwt_secret_key.encode(), signing_input, hashlib.sha256).digest()
    return f"{header_segment}.{payload_segment}.{_base64url_encode(signature)}"


def verify_token(token: str) -> dict[str, Any]:
    try:
        header_segment, payload_segment, signature = token.split(".")
    except ValueError as exc:
        raise ValueError("Token invalid") from exc

    signing_input = f"{header_segment}.{payload_segment}".encode()
    expected_signature = _base64url_encode(
        hmac.new(settings.jwt_secret_key.encode(), signing_input, hashlib.sha256).digest()
    )
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("Token signature invalid")

    payload = json.loads(_base64url_decode(payload_segment))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("Token expired")
    return payload


def hash_password(password: str) -> str:
    try:
        import bcrypt
    except ImportError:
        bcrypt = None

    if bcrypt is not None:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"{salt}:{digest}"


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        import bcrypt
    except ImportError:
        bcrypt = None

    if bcrypt is not None:
        try:
            return bcrypt.checkpw(password.encode(), hashed_password.encode())
        except ValueError:
            return False

    if ":" not in hashed_password:
        return False
    salt, digest = hashed_password.split(":", 1)
    computed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return hmac.compare_digest(computed, digest)
