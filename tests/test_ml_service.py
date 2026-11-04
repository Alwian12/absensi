"""Tests for the standalone face ML service app (auth, size, endpoints)."""
import pytest
from fastapi.testclient import TestClient

from ml_service import main as ml_main
from ml_service.main import app

IMG_B64 = "A" * 40  # valid base64, length >= 32


class _StubService:
    name = "stub"

    def is_ready(self) -> bool:
        return True

    def check_liveness(self, _b):
        return {"passed": True, "score": 10.0, "method": "stub"}

    def register_embedding(self, _b, user_id):
        return {
            "user_id": user_id,
            "embedding": [0.1],
            "engine": "stub",
            "dim": 1,
            "thumbnail": "data:image/jpeg;base64,AAAA",
            "quality": {"ok": True, "samples_used": 1},
        }

    def register_embedding_multi(self, images, user_id):
        return {
            "user_id": user_id,
            "embedding": [0.1],
            "engine": "stub",
            "dim": 1,
            "thumbnail": "data:image/jpeg;base64,AAAA",
            "quality": {"samples_used": len(images), "min_pair_similarity": 0.9},
        }

    def verify_embedding(self, _b, _emb, _threshold=None):
        return {"matched": True, "similarity": 1.0}


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    monkeypatch.setattr(ml_main.settings, "face_service_token", "secret-token")
    monkeypatch.setattr(ml_main, "face_service", _StubService())


def test_health_reports_model_state() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["model_ready"] is True


def test_face_endpoints_require_service_token() -> None:
    response = TestClient(app).post("/face/verify", json={"image_base64": IMG_B64, "embedding": [0.1]})
    assert response.status_code == 401


def test_verify_with_valid_token() -> None:
    response = TestClient(app).post(
        "/face/verify",
        headers={"X-Service-Token": "secret-token"},
        json={"image_base64": IMG_B64, "embedding": [0.1]},
    )
    assert response.status_code == 200
    assert response.json()["matched"] is True


def test_register_omits_thumbnail_by_default() -> None:
    response = TestClient(app).post(
        "/face/register",
        headers={"X-Service-Token": "secret-token"},
        json={"image_base64": IMG_B64, "user_id": 5},
    )
    assert response.status_code == 200
    assert "thumbnail" not in response.json()


def test_register_multi_uses_multiple_samples() -> None:
    response = TestClient(app).post(
        "/face/register",
        headers={"X-Service-Token": "secret-token"},
        json={"images_base64": [IMG_B64, IMG_B64, IMG_B64], "user_id": 6, "include_thumbnail": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["quality"]["samples_used"] == 3
    assert body["thumbnail"].startswith("data:image/jpeg")


def test_register_without_images_is_rejected() -> None:
    response = TestClient(app).post(
        "/face/register",
        headers={"X-Service-Token": "secret-token"},
        json={"user_id": 6},
    )
    assert response.status_code == 400


def test_oversized_payload_is_rejected() -> None:
    oversized = "A" * (ml_main.settings.face_max_image_bytes + 1)
    response = TestClient(app).post(
        "/face/liveness",
        headers={"X-Service-Token": "secret-token"},
        json={"image_base64": oversized},
    )
    assert response.status_code == 413
