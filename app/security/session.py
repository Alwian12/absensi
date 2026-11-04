"""Signed session cookie for web/API authentication.

This replaces the legacy scheme that trusted a raw, unsigned ``user_id`` cookie
(audit finding **F-01**: authentication bypass / IDOR). The session token is an
HMAC-SHA256 signed payload binding ``user_id`` + ``session_version`` + expiry, so
a client can no longer become an arbitrary user by editing a cookie.

``session_version`` lets admins invalidate every existing session of a user
(force-logout) without touching other users.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.authentication.jwt_handler import verify_token
from app.config import settings
from app.models.user import User

SESSION_COOKIE = "session"
# Legacy cookie names are only referenced so we can actively clear them.
LEGACY_USER_COOKIE = "user_id"
LEGACY_VERSION_COOKIE = "session_ver"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(segment: str) -> str:
    signature = hmac.new(settings.jwt_secret_key.encode(), segment.encode(), hashlib.sha256).digest()
    return _b64url_encode(signature)


def create_session_token(user_id: int, session_version: int) -> str:
    """Return a tamper-proof session token bound to the user + session version."""
    payload = {
        "sub": int(user_id),
        "ver": int(session_version),
        "exp": int(time.time()) + settings.jwt_expire_minutes * 60,
    }
    segment = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    return f"{segment}.{_sign(segment)}"


def read_session_token(token: str) -> dict[str, Any] | None:
    """Verify signature + expiry; return the payload or ``None`` if invalid."""
    try:
        segment, signature = token.split(".", 1)
    except (AttributeError, ValueError):
        return None
    if not hmac.compare_digest(_sign(segment), signature):
        return None
    try:
        payload: dict[str, Any] = json.loads(_b64url_decode(segment))
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


def _user_from_bearer(db: Session, authorization: str | None) -> User | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = verify_token(token)
        user_id = int(payload["sub"])
    except Exception:
        return None
    return db.query(User).filter(User.id == user_id, User.is_active == True).first()


def _user_from_session_cookie(db: Session, request: Request) -> User | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    payload = read_session_token(raw)
    if not payload:
        return None
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        return None
    if int(payload.get("ver", 1)) != (user.session_version or 1):
        return None
    return user


def resolve_user(request: Request, db: Session, authorization: str | None = None) -> User | None:
    """Resolve the authenticated user from a Bearer token or the signed session cookie."""
    if authorization is None:
        authorization = request.headers.get("authorization") or request.headers.get("Authorization")
    user = _user_from_bearer(db, authorization)
    if user:
        return user
    return _user_from_session_cookie(db, request)


def require_user(
    request: Request,
    db: Session,
    authorization: str | None = None,
) -> User:
    """Shared dependency for API routers: resolve the user or raise 401.

    Single implementation replacing the four identical copies previously kept in
    attendance.py, journal.py, reports.py and dashboard.py (audit finding F-20).
    """
    user = resolve_user(request, db, authorization)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    return user
