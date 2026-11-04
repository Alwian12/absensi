from fastapi.testclient import TestClient

from app.main import app
from app.security.csrf import CSRF_COOKIE_NAME, generate_csrf_token
from app.security.session import SESSION_COOKIE


client = TestClient(app)


def test_health_endpoint_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_login_page_renders() -> None:
    response = client.get("/login")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


def test_login_with_invalid_credentials_returns_error_page() -> None:
    # Regression: a failed login used to return a bare `null` JSON body (no response).
    response = TestClient(app).post(
        "/login",
        data={"email": "tidak-ada@example.test", "password": "salah"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Username/email atau password salah" in response.text


def test_dashboard_requires_authentication() -> None:
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == "/login"


def test_dashboard_api_requires_authentication() -> None:
    response = client.get("/api/dashboard")
    assert response.status_code == 401


def test_forged_user_id_cookie_is_rejected() -> None:
    # Regression for audit finding F-01: an unsigned user_id cookie must never authenticate.
    forged = TestClient(app)
    forged.cookies.set("user_id", "1")
    response = forged.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == "/login"


def test_invalid_journal_signature_token_returns_not_found() -> None:
    response = client.get("/journal-signature/invalid-token")
    assert response.status_code == 404


def test_face_verify_requires_authentication() -> None:
    # Regression: unauthenticated API calls must reach the auth layer directly without being blocked by CSRF.
    response = client.post(
        "/api/face/verify",
        json={
            "image_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAoMBgQmL9z8AAAAASUVORK5CYII=",
            "action": "checkin",
        },
    )
    assert response.status_code == 401


def test_face_verify_cookie_auth_rejected_without_csrf_token() -> None:
    # Regression for audit finding F-05: cookie-authenticated requests must require CSRF validation.
    auth_client = TestClient(app)
    auth_client.cookies.set(SESSION_COOKIE, "dummy-session-token")
    response = auth_client.post(
        "/api/face/verify",
        json={
            "image_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAoMBgQmL9z8AAAAASUVORK5CYII=",
            "action": "checkin",
        },
    )
    assert response.status_code == 403
    assert "detail" in response.json()


def test_face_verify_pure_bearer_token_bypasses_csrf() -> None:
    # API clients with Bearer token are not vulnerable to CSRF and bypass CSRF check
    bearer_client = TestClient(app)
    response = bearer_client.post(
        "/api/face/verify",
        headers={"Authorization": "Bearer invalid.jwt.token"},
        json={
            "image_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAoMBgQmL9z8AAAAASUVORK5CYII=",
            "action": "checkin",
        },
    )
    # The request bypasses CSRF and reaches auth layer (returning 401 Unauthorized for invalid JWT, not 403 CSRF)
    assert response.status_code == 401


def test_face_verify_cookie_auth_passes_with_valid_csrf_token() -> None:
    csrf = generate_csrf_token()
    auth_client = TestClient(app)
    auth_client.cookies.set(SESSION_COOKIE, "dummy-session-token")
    auth_client.cookies.set(CSRF_COOKIE_NAME, csrf)
    response = auth_client.post(
        "/api/face/verify",
        headers={"X-CSRF-Token": csrf},
        json={
            "image_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAoMBgQmL9z8AAAAASUVORK5CYII=",
            "action": "checkin",
        },
    )
    # CSRF check passed (not 403); reaches auth check
    assert response.status_code != 403
