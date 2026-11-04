import pytest
from pydantic import ValidationError

from app.config import Settings
from app.security.csrf import generate_csrf_token, validate_csrf_token
from app.security.face_crypto import decrypt_text, encrypt_text
from app.security.session import create_session_token, read_session_token
from app.services.rate_limiter import DatabaseRateLimiter, SimpleRateLimiter


def test_session_token_round_trip() -> None:
    token = create_session_token(42, 3)
    payload = read_session_token(token)
    assert payload is not None
    assert payload["sub"] == 42
    assert payload["ver"] == 3


def test_session_token_rejects_tampering_and_garbage() -> None:
    token = create_session_token(42, 3)
    segment, signature = token.split(".", 1)
    flipped = "A" if segment[-1] != "A" else "B"
    tampered = f"{segment[:-1]}{flipped}.{signature}"
    assert read_session_token(tampered) is None
    assert read_session_token("garbage") is None
    assert read_session_token("") is None


def test_csrf_token_validation() -> None:
    token = generate_csrf_token()
    assert validate_csrf_token(token)
    assert not validate_csrf_token("raw.value")
    assert not validate_csrf_token(token.rsplit(".", 1)[0] + ".deadbeef")


def _multipart_body(fields: list[tuple[str, str]], boundary: str = "----TestBoundary") -> tuple[bytes, str]:
    parts = []
    for name, value in fields:
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        )
    parts.append(f"--{boundary}--\r\n")
    body = "".join(parts).encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


def test_csrf_cookie_is_readable_by_javascript() -> None:
    # Regression: the cookie was written with "HttpOnly=False", which browsers still treat
    # as HttpOnly. JS could not read it, so no form ever received a csrf_token and every
    # admin POST (edit/delete) was rejected by the CSRF middleware.
    from fastapi.testclient import TestClient

    from app.main import app

    set_cookie = TestClient(app).get("/login").headers.get("set-cookie", "")
    assert "csrf_token_v2=" in set_cookie
    assert "httponly" not in set_cookie.lower()


def test_csrf_multipart_token_found_regardless_of_field_order() -> None:
    from app.security.csrf import _extract_form_token

    token = generate_csrf_token()
    # csrf_token is NOT the first field (previously a byte-scan weak point, F-08).
    body, content_type = _multipart_body(
        [("username", "budi"), ("catatan", 'kata "kutip" & ampersand'), ("csrf_token", token)]
    )
    assert _extract_form_token(body, content_type) == token


def test_csrf_urlencoded_token_is_extracted() -> None:
    from app.security.csrf import _extract_form_token

    token = generate_csrf_token()
    body = f"username=budi&csrf_token={token}".encode()
    assert _extract_form_token(body, "application/x-www-form-urlencoded") == token


def test_face_crypto_round_trip_and_tamper() -> None:
    secret = '{"embedding": [0.1, 0.2, 0.3]}'
    ciphertext = encrypt_text(secret)
    assert ciphertext != secret
    assert decrypt_text(ciphertext) == secret
    with pytest.raises(ValueError):
        decrypt_text(ciphertext[:-4] + "AAAA")


def test_settings_rejects_weak_secret_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(debug=False, jwt_secret_key="change-me")


def test_settings_allows_weak_secret_in_debug() -> None:
    config = Settings(debug=True, jwt_secret_key="change-me")
    assert config.jwt_secret_key == "change-me"


def test_simple_rate_limiter_blocks_after_max_attempts() -> None:
    limiter = SimpleRateLimiter(max_attempts=2, window_seconds=60)
    assert not limiter.is_blocked("k")
    limiter.record_attempt("k")
    assert not limiter.is_blocked("k")
    limiter.record_attempt("k")
    assert limiter.is_blocked("k")
    assert limiter.remaining_seconds("k") > 0
    limiter.reset("k")
    assert not limiter.is_blocked("k")


def test_database_rate_limiter_persists_and_resets() -> None:
    limiter = DatabaseRateLimiter(max_attempts=2, window_seconds=60)
    key = "test:rate-limit:persist"
    limiter.reset(key)
    try:
        assert not limiter.is_blocked(key)
        limiter.record_attempt(key)
        limiter.record_attempt(key)
        assert limiter.is_blocked(key)

        # A fresh instance sees the same state (survives restart / other workers).
        assert DatabaseRateLimiter(max_attempts=2, window_seconds=60).is_blocked(key)
    finally:
        limiter.reset(key)
    assert not limiter.is_blocked(key)


# ──────────────────────────────────────────────────────────────────────────────
# Opsi D — CSRF middleware bearer-bypass & JSON header enforcement
# ──────────────────────────────────────────────────────────────────────────────

def test_csrf_json_with_bearer_token_is_bypassed() -> None:
    """JSON POST with Authorization: Bearer must bypass CSRF check (API client path)."""
    from app.security.csrf import _has_bearer_token

    bearer_headers = [(b"authorization", b"Bearer eyJhbGci.payload.sig")]
    assert _has_bearer_token(bearer_headers) is True


def test_csrf_json_without_bearer_is_not_bypassed() -> None:
    """JSON POST without Authorization header must NOT bypass CSRF (browser path)."""
    from app.security.csrf import _has_bearer_token

    assert _has_bearer_token([]) is False
    assert _has_bearer_token([(b"content-type", b"application/json")]) is False
    # Basic auth is not Bearer
    assert _has_bearer_token([(b"authorization", b"Basic dXNlcjpwYXNz")]) is False


def test_csrf_has_bearer_token_case_insensitive() -> None:
    """Bearer check is case-insensitive for header name and scheme."""
    from app.security.csrf import _has_bearer_token

    assert _has_bearer_token([(b"Authorization", b"Bearer token")]) is True
    assert _has_bearer_token([(b"AUTHORIZATION", b"BEARER token")]) is True


def test_csrf_json_api_blocked_for_session_cookie_without_csrf_header() -> None:
    """JSON POST with session cookie but no CSRF header → 403."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.security.session import SESSION_COOKIE

    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, "dummy-session-token")
    response = client.post(
        "/api/attendance/checkin",
        json={"image_base64": "x", "latitude": 0.0, "longitude": 0.0},
    )
    # Session cookie present, no X-CSRF-Token header → must be blocked by middleware
    assert response.status_code == 403
    assert "CSRF" in response.text or "csrf" in response.text.lower()


def test_csrf_json_api_passes_with_valid_header_and_cookie() -> None:
    """JSON POST with session cookie and matching X-CSRF-Token header and cookie passes CSRF middleware."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.security.csrf import CSRF_COOKIE_NAME, generate_csrf_token
    from app.security.session import SESSION_COOKIE

    csrf = generate_csrf_token()
    c = TestClient(app)
    c.cookies.set(SESSION_COOKIE, "dummy-session-token")
    c.cookies.set(CSRF_COOKIE_NAME, csrf)
    response = c.post(
        "/api/attendance/checkin",
        headers={"X-CSRF-Token": csrf},
        json={"image_base64": "x", "latitude": 0.0, "longitude": 0.0},
    )
    # CSRF middleware lets the request through (not 403).
    assert response.status_code != 403


def test_csrf_json_api_without_session_cookie_passes_csrf_to_auth() -> None:
    """JSON POST without session cookie is not an ambient credential request and reaches auth layer."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    response = client.post(
        "/api/attendance/checkin",
        json={"image_base64": "A" * 64, "latitude": 0.0, "longitude": 0.0, "accuracy_m": 10.0},
    )
    # Reaches auth layer, resulting in 401 Unauthorized (not 403 CSRF block)
    assert response.status_code == 401
