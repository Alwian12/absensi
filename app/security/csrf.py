"""Double-submit cookie CSRF protection."""
import hashlib
import hmac
import secrets
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send, Message

from app.config import settings

_COOKIE = "csrf_token"
_FORM_FIELD = "csrf_token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
_SKIP_PREFIXES = ("/api/", "/face/", "/static/")
# Pre-auth forms don't carry session state so CSRF risk is lower
_SKIP_PATHS = {"/login", "/register"}


def _sign(token: str) -> str:
    return hmac.new(settings.jwt_secret_key.encode(), token.encode(), hashlib.sha256).hexdigest()[:16]


def generate_csrf_token() -> str:
    raw = secrets.token_hex(20)
    return f"{raw}.{_sign(raw)}"


def validate_csrf_token(token: str) -> bool:
    try:
        raw, sig = token.rsplit(".", 1)
        return hmac.compare_digest(_sign(raw), sig)
    except Exception:
        return False


class CSRFMiddleware:
    """Pure ASGI CSRF middleware that caches the request body so downstream handlers can still read it."""

    def __init__(self, app: ASGIApp, **kwargs) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        method = request.method
        path = request.url.path

        # Set CSRF cookie on every response
        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                if not request.cookies.get(_COOKIE):
                    token = generate_csrf_token()
                    headers = list(message.get("headers", []))
                    cookie_val = f"{_COOKIE}={token}; Path=/; SameSite=Lax; HttpOnly=False"
                    if settings.cookie_secure:
                        cookie_val += "; Secure"
                    headers.append((b"set-cookie", cookie_val.encode()))
                    message = {**message, "headers": headers}
            await send(message)

        # Skip safe methods and excluded paths
        if method in _SAFE_METHODS or any(path.startswith(p) for p in _SKIP_PREFIXES) or path in _SKIP_PATHS:
            await self.app(scope, receive, send_with_cookie)
            return

        # Read body once, then replay it for downstream handlers
        body = await request.body()

        # Parse form data manually from cached body to get csrf_token
        cookie_token = request.cookies.get(_COOKIE, "")
        form_token = ""
        content_type = request.headers.get("content-type", "")

        if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            try:
                from urllib.parse import parse_qs
                if "application/x-www-form-urlencoded" in content_type:
                    parsed = parse_qs(body.decode("utf-8", errors="replace"))
                    tokens = parsed.get(_FORM_FIELD, [""])
                    form_token = tokens[0] if tokens else ""
                else:
                    marker = b'name="csrf_token"'
                    marker_index = body.find(marker)
                    if marker_index >= 0:
                        value_start = body.find(b"\r\n\r\n", marker_index)
                        if value_start >= 0:
                            value_start += 4
                            value_end = body.find(b"\r\n", value_start)
                            form_token = body[value_start:value_end].decode("utf-8", errors="replace").strip()
            except Exception:
                pass
        elif "application/json" in content_type:
            # JSON requests are protected by CORS; skip CSRF check
            async def replay(message_type: str = "http.request"):
                return {"type": message_type, "body": body, "more_body": False}
            await self.app(scope, replay, send_with_cookie)
            return

        # Validate
        if not cookie_token or not form_token or cookie_token != form_token or not validate_csrf_token(cookie_token):
            async def _send_403(send_fn=send):
                await send_fn({"type": "http.response.start", "status": 303,
                               "headers": [(b"location", b"/dashboard?error=Permintaan tidak valid. Coba lagi.")]})
                await send_fn({"type": "http.response.body", "body": b""})
            await _send_403()
            return

        # Replay body for downstream
        async def replay(message_type: str = "http.request"):
            return {"type": message_type, "body": body, "more_body": False}

        await self.app(scope, replay, send_with_cookie)

