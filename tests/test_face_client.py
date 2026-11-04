"""Tests for the standalone face ML service client (fail-closed HTTP contract)."""
import json

import pytest

from app.ai.face_client import FaceServiceClient, HttpResponse
from app.ai.face_service import FaceRecognitionError

IMG = b"\x00" * 64


def _client(transport) -> FaceServiceClient:
    return FaceServiceClient("http://ml.local", "tok", 5.0, transport=transport)


def test_verify_embedding_sends_token_and_returns_payload() -> None:
    captured = {}

    def transport(url, body, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = json.loads(body)
        return HttpResponse(200, {}, json.dumps({"matched": True, "similarity": 0.9}).encode())

    result = _client(transport).verify_embedding(IMG, [0.1, 0.2])
    assert result["matched"] is True
    assert captured["url"].endswith("/face/verify")
    assert captured["headers"]["X-Service-Token"] == "tok"
    assert captured["payload"]["embedding"] == [0.1, 0.2]


def test_transport_error_maps_to_service_unavailable() -> None:
    def transport(url, body, headers, timeout):
        raise OSError("connection refused")

    with pytest.raises(FaceRecognitionError) as excinfo:
        _client(transport).verify_embedding(IMG, [0.1])
    assert excinfo.value.reason_code == "service_unavailable"


def test_server_error_maps_to_service_unavailable() -> None:
    def transport(url, body, headers, timeout):
        return HttpResponse(503, {}, b"{}")

    with pytest.raises(FaceRecognitionError) as excinfo:
        _client(transport).check_liveness(IMG)
    assert excinfo.value.reason_code == "service_unavailable"


def test_face_reason_code_is_propagated() -> None:
    def transport(url, body, headers, timeout):
        return HttpResponse(
            400,
            {"X-Reason-Code": "no_face"},
            json.dumps({"detail": "Wajah tidak terdeteksi."}).encode(),
        )

    with pytest.raises(FaceRecognitionError) as excinfo:
        _client(transport).register_embedding(IMG, 1)
    assert excinfo.value.reason_code == "no_face"
    assert "terdeteksi" in str(excinfo.value)
