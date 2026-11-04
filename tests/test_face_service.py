"""Fail-closed behaviour tests for the face recognition pipeline (PRD BAB X)."""
import numpy as np
import pytest

from app.ai import face_service as fs
from app.ai.face_service import FaceRecognitionError, FaceRecognitionService


class _Face:
    def __init__(self, bbox, embedding):
        self.bbox = bbox
        self.embedding = embedding


class _FakeApp:
    """Stand-in for insightface FaceAnalysis.get()."""

    def __init__(self, faces):
        self._faces = faces

    def get(self, _image):
        return self._faces


def _service_with_faces(monkeypatch, faces):
    service = FaceRecognitionService()
    monkeypatch.setattr(service, "_ensure_insight_ready", lambda: None)
    service._insight_attempted = True
    service._insight_ready = True
    service._insight_app = _FakeApp(faces)
    monkeypatch.setattr(service, "_decode_image", lambda _b: np.zeros((200, 200, 3), dtype=np.uint8))
    monkeypatch.setattr(service, "_face_quality", lambda _img, _bbox: {"ok": True, "sharpness": 100.0})
    return service


def test_extract_embedding_fails_closed_when_model_unavailable(monkeypatch) -> None:
    service = FaceRecognitionService()
    monkeypatch.setattr(service, "_ensure_insight_ready", lambda: None)
    service._insight_attempted = True
    service._insight_ready = False
    service._insight_app = None
    monkeypatch.setattr(service, "_decode_image", lambda _b: np.zeros((10, 10, 3), dtype=np.uint8))

    with pytest.raises(FaceRecognitionError) as excinfo:
        service.extract_embedding(b"x")
    assert excinfo.value.reason_code == "model_unavailable"


def test_extract_embedding_rejects_missing_face(monkeypatch) -> None:
    service = _service_with_faces(monkeypatch, [])
    with pytest.raises(FaceRecognitionError) as excinfo:
        service.extract_embedding(b"x")
    assert excinfo.value.reason_code == "no_face"


def test_extract_embedding_rejects_multiple_faces(monkeypatch) -> None:
    faces = [
        _Face((0, 0, 140, 140), np.ones(4, dtype=np.float32)),
        _Face((0, 0, 100, 100), np.ones(4, dtype=np.float32)),
    ]
    service = _service_with_faces(monkeypatch, faces)
    with pytest.raises(FaceRecognitionError) as excinfo:
        service.extract_embedding(b"x")
    assert excinfo.value.reason_code == "multiple_faces"


def test_extract_embedding_rejects_low_quality(monkeypatch) -> None:
    service = _service_with_faces(monkeypatch, [_Face((0, 0, 140, 140), np.ones(4, dtype=np.float32))])
    monkeypatch.setattr(
        service,
        "_face_quality",
        lambda _img, _bbox: {"ok": False, "reason_code": "face_blurry", "message": "buram"},
    )
    with pytest.raises(FaceRecognitionError) as excinfo:
        service.extract_embedding(b"x")
    assert excinfo.value.reason_code == "face_blurry"


def test_extract_embedding_returns_normalized_vector(monkeypatch) -> None:
    service = _service_with_faces(
        monkeypatch, [_Face((0, 0, 140, 140), np.array([3.0, 4.0], dtype=np.float32))]
    )
    result = service.extract_embedding(b"x")
    assert result["engine"] == "insightface"
    assert result["dim"] == 2
    norm = sum(value * value for value in result["embedding"])
    assert abs(norm - 1.0) < 1e-5


def test_verify_embedding_matches_identical_template(monkeypatch) -> None:
    service = _service_with_faces(
        monkeypatch, [_Face((0, 0, 140, 140), np.array([1.0, 0.0], dtype=np.float32))]
    )
    result = service.verify_embedding(b"x", [1.0, 0.0])
    assert result["matched"] is True
    assert result["similarity"] == 1.0


def test_verify_embedding_rejects_dimension_mismatch(monkeypatch) -> None:
    service = _service_with_faces(
        monkeypatch, [_Face((0, 0, 140, 140), np.array([1.0, 0.0], dtype=np.float32))]
    )
    with pytest.raises(FaceRecognitionError) as excinfo:
        service.verify_embedding(b"x", [1.0, 0.0, 0.0])
    assert excinfo.value.reason_code == "embedding_dim_mismatch"


def _multi_service(monkeypatch, embeddings):
    service = FaceRecognitionService()
    sequence = iter(embeddings)

    def _fake_extract(_b):
        vector = next(sequence)
        return {"embedding": vector, "engine": "insightface", "dim": len(vector), "quality": {"sharpness": 100.0}}

    monkeypatch.setattr(service, "extract_embedding", _fake_extract)
    monkeypatch.setattr(service, "extract_face_thumbnail", lambda _b, size=160: None)
    return service


def test_register_multi_rejects_too_few_samples(monkeypatch) -> None:
    service = _multi_service(monkeypatch, [[1.0, 0.0], [1.0, 0.0]])
    with pytest.raises(FaceRecognitionError) as excinfo:
        service.register_embedding_multi([b"a", b"b"], 1)
    assert excinfo.value.reason_code == "too_few_samples"


def test_register_multi_rejects_inconsistent_samples(monkeypatch) -> None:
    service = _multi_service(monkeypatch, [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]])
    with pytest.raises(FaceRecognitionError) as excinfo:
        service.register_embedding_multi([b"a", b"b", b"c"], 1)
    assert excinfo.value.reason_code == "inconsistent_samples"


def test_register_multi_aggregates_consistent_samples(monkeypatch) -> None:
    service = _multi_service(
        monkeypatch, [[1.0, 0.0], [1.0, 0.01], [0.99, 0.0]]
    )
    result = service.register_embedding_multi([b"a", b"b", b"c"], 7)
    assert result["user_id"] == 7
    assert result["quality"]["samples_used"] == 3
    assert result["quality"]["min_pair_similarity"] > 0.5
    norm = sum(value * value for value in result["embedding"])
    assert abs(norm - 1.0) < 1e-5


def test_check_liveness_fails_closed_without_cv2(monkeypatch) -> None:
    service = FaceRecognitionService()
    monkeypatch.setattr(fs, "cv2", None)
    assert service.check_liveness(b"x")["passed"] is False


def test_check_liveness_fails_closed_on_decode_error(monkeypatch) -> None:
    service = FaceRecognitionService()

    def _boom(_b):
        raise ValueError("bad image")

    monkeypatch.setattr(service, "_decode_image", _boom)
    assert service.check_liveness(b"x")["passed"] is False
