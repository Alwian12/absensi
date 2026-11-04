"""Double-submit cookie CSRF protection."""
import hashlib
import hmac
import secrets
from urllib.parse import urlencode, urlsplit

from fastapi import Request
from starlette.types import ASGIApp, Receive, Scope, Send, Message

from app.config import settings
from app.security.session import SESSION_COOKIE

# The cookie name is versioned: releases that wrote "HttpOnly=False" still produced an
# HttpOnly cookie, which JS cannot read, so existing browser cookies must be abandoned.
_COOKIE = "csrf_token_v2"
_LEGACY_COOKIE = "csrf_token"
_FORM_FIELD = "csrf_token"
# Public aliases (tests / integrations need the exact names).
CSRF_COOKIE_NAME = _COOKIE
CSRF_FORM_FIELD = _FORM_FIELD
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# Paths excluded from CSRF regardless of method.
#   /static/ — never mutable, no state change.
# NOTE: /api/ and /face/ are intentionally NOT in this list.
#   Bearer-authenticated JSON requests skip CSRF via the bearer-check logic below.
#   Browser-originated JSON POSTs (cookie session) must supply X-CSRF-Token header.
_SKIP_PREFIXES = ("/static/",)

# Pre-auth forms don't carry session state so CSRF risk is lower.
_SKIP_PATHS = {"/login", "/register"}

# Header name JS must send when calling JSON endpoints from a browser session.
_CSRF_HEADER = "x-csrf-token"


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


def _safe_referer_path(referer: str) -> str:
    """Return the local path of a same-origin referer (or "" when unusable)."""
    if not referer:
        return ""
    try:
        parts = urlsplit(referer)
    except Exception:
        return ""
    if parts.scheme not in ("http", "https"):
        return ""
    path = parts.path or "/"
    if not path.startswith("/") or path.startswith("//"):
        return ""
    return path


def _extract_form_token(body: bytes, content_type: str) -> str:
    """Return the ``csrf_token`` field from a urlencoded or multipart body."""
    if "application/x-www-form-urlencoded" in content_type:
        try:
            from urllib.parse import parse_qs

            parsed = parse_qs(body.decode("utf-8", errors="replace"))
            tokens = parsed.get(_FORM_FIELD, [""])
            return tokens[0] if tokens else ""
        except Exception:
            return ""

    if "multipart/form-data" in content_type:
        try:
            marker = b'name="csrf_token"'
            marker_index = body.find(marker)
            if marker_index < 0:
                return ""
            # Skip the field's Content-Disposition line, then read header block end.
            value_start = body.find(b"\r\n\r\n", marker_index)
            if value_start < 0:
                return ""
            value_start += 4
            value_end = body.find(b"\r\n", value_start)
            if value_end < 0:
                value_end = len(body)
            return body[value_start:value_end].decode("utf-8", errors="replace").strip()
        except Exception:
            return ""

    return ""


def _has_bearer_token(headers: list) -> bool:
    """Return True when the request carries an Authorization: Bearer ... header.

    True-API clients (mobile app, kiosk hardware, external integrations) always
    authenticate via Bearer token — they are not vulnerable to CSRF because they
    do not rely on browser cookies.  Browser-based code never sends a Bearer
    header, so this is a reliable discriminator.
    """
    for name, value in headers:
        if name.lower() == b"authorization":
            return value.strip().lower().startswith(b"bearer ")
    return False


class CSRFMiddleware:
    """Pure ASGI CSRF middleware that caches the request body so downstream handlers can still read it.

    Protection matrix
    -----------------
    Method      Content-Type          Auth              Action
    ----------  --------------------  ----------------  -----------------------------------------------
    GET/HEAD/…  any                   any               Skip (safe method)
    POST/…      form / multipart      any               Validate double-submit cookie + form field
    POST/…      application/json      Bearer token      Skip — API client, not CSRF-vulnerable
    POST/…      application/json      cookie/anonymous  Require X-CSRF-Token header == cookie value
    POST/…      other                 any               Validate double-submit cookie + form field
    """

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
                headers = list(message.get("headers", []))
                if not request.cookies.get(_COOKIE):
                    token = generate_csrf_token()
                    # No HttpOnly: the double-submit pattern needs JS to read this cookie
                    # and mirror it into a hidden form field or X-CSRF-Token header.
                    cookie_val = f"{_COOKIE}={token}; Path=/; SameSite=Lax"
                    if settings.cookie_secure:
                        cookie_val += "; Secure"
                    headers.append((b"set-cookie", cookie_val.encode()))
                if request.cookies.get(_LEGACY_COOKIE):
                    headers.append((
                        b"set-cookie",
                        f"{_LEGACY_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax".encode(),
                    ))
                message = {**message, "headers": headers}
            await send(message)

        # ── Skip safe methods and always-excluded paths ────────────────────
        if method in _SAFE_METHODS or any(path.startswith(p) for p in _SKIP_PREFIXES) or path in _SKIP_PATHS:
            await self.app(scope, receive, send_with_cookie)
            return

        raw_headers = scope.get("headers", [])
        has_bearer = _has_bearer_token(raw_headers)
        has_session = bool(request.cookies.get(SESSION_COOKIE))

        # ── Pure Bearer JWT requests ───────────────────────────────────────
        # True-API clients (mobile app, kiosk hardware, external integrations)
        # authenticate via Bearer token without web session cookies.
        # They do not rely on browser ambient credentials and are exempt from CSRF.
        if has_bearer and not has_session:
            await self.app(scope, receive, send_with_cookie)
            return

        # ── Requests without web session cookie ─────────────────────────────
        # CSRF is strictly an ambient credential (session cookie) attack vector.
        # Requests that do not carry a web session cookie have no browser session
        # to forge; they proceed to downstream authentication / route handlers.
        if not has_session:
            await self.app(scope, receive, send_with_cookie)
            return

        # ── From here on, request carries web session cookie: ENFORCE CSRF ─
        # Read body once, then replay it for downstream handlers
        body = await request.body()
        content_type = request.headers.get("content-type", "")

        # ── JSON requests (browser AJAX / fetch with session cookie) ───────
        if "application/json" in content_type:
            # Browser-originated JSON POST (cookie session): require the caller
            # to echo the CSRF cookie in the X-CSRF-Token request header.
            cookie_token = request.cookies.get(_COOKIE, "")
            header_token = request.headers.get(_CSRF_HEADER, "")

            valid = (
                cookie_token
                and header_token
                and validate_csrf_token(cookie_token)
                and hmac.compare_digest(cookie_token, header_token)
            )
            if not valid:
                _body = b'{"detail":"CSRF token missing or invalid"}'
                async def _send_403_json(send_fn=send, resp_body=_body):
                    await send_fn({
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(resp_body)).encode()),
                        ],
                    })
                    await send_fn({"type": "http.response.body", "body": resp_body})
                await _send_403_json()
                return

            async def replay_json(message_type: str = "http.request"):
                return {"type": message_type, "body": body, "more_body": False}
            await self.app(scope, replay_json, send_with_cookie)
            return

        # ── Form / multipart requests (browser form submit with session cookie)
        cookie_token = request.cookies.get(_COOKIE, "")
        form_token = _extract_form_token(body, content_type)

        if not cookie_token or not form_token or cookie_token != form_token or not validate_csrf_token(cookie_token):
            back = _safe_referer_path(request.headers.get("referer", "")) or "/dashboard"
            separator = "&" if "?" in back else "?"
            location = f"{back}{separator}" + urlencode({"error": "Permintaan tidak valid. Silakan muat ulang halaman lalu coba lagi."})

            async def _send_303(send_fn=send):
                await send_fn({"type": "http.response.start", "status": 303,
                               "headers": [(b"location", location.encode("utf-8"))]})
                await send_fn({"type": "http.response.body", "body": b""})
            await _send_303()
            return

        # Replay body for downstream
        async def replay_form(message_type: str = "http.request"):
            return {"type": message_type, "body": body, "more_body": False}

        await self.app(scope, replay_form, send_with_cookie)
