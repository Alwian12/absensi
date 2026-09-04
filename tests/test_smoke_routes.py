from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_endpoint_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_login_page_renders() -> None:
    response = client.get("/login")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


def test_dashboard_requires_authentication() -> None:
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == "/login"


def test_dashboard_api_responds_with_aggregate_counts() -> None:
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    payload = response.json()
    assert "total_users" in payload
    assert "total_attendance" in payload
    assert "total_journals" in payload


def test_invalid_journal_signature_token_returns_not_found() -> None:
    response = client.get("/journal-signature/invalid-token")
    assert response.status_code == 404


def test_face_verify_requires_authentication() -> None:
    response = client.post(
        "/api/face/verify",
        json={
            "image_base64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAoMBgQmL9z8AAAAASUVORK5CYII=",
            "action": "checkin",
        },
    )
    assert response.status_code == 401
