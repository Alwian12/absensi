import base64
import hashlib
import hmac
from datetime import UTC, datetime

from app.config import settings


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode((raw + padding).encode("utf-8"))


def generate_journal_signature_token(journal_id: int, supervisor_id: int, issued_at: int | None = None) -> str:
    ts = issued_at or int(datetime.now(UTC).timestamp())
    payload = f"{journal_id}:{supervisor_id}:{ts}".encode("utf-8")
    secret = settings.jwt_secret_key.encode("utf-8")
    digest = hmac.new(secret, payload, hashlib.sha256).digest()
    return f"{_b64url_encode(payload)}.{_b64url_encode(digest)}"


def verify_journal_signature_token(token: str) -> tuple[int, int, int]:
    try:
        payload_part, sig_part = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("Format token tidak valid") from exc

    payload = _b64url_decode(payload_part)
    provided_sig = _b64url_decode(sig_part)
    expected_sig = hmac.new(settings.jwt_secret_key.encode("utf-8"), payload, hashlib.sha256).digest()

    if not hmac.compare_digest(provided_sig, expected_sig):
        raise ValueError("Token tanda tangan tidak valid")

    try:
        journal_raw, supervisor_raw, ts_raw = payload.decode("utf-8").split(":", 2)
        return int(journal_raw), int(supervisor_raw), int(ts_raw)
    except Exception as exc:
        raise ValueError("Payload token tidak valid") from exc
