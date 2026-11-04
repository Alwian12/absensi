"""Standalone face ML service (FastAPI).

Runs the Computer-Vision model in a **separate process** so the main web
application never needs the CV stack, keeps no database credentials, and never
delegates the attendance decision. It only returns structured results
(face found / quality / embedding / similarity / liveness) plus a machine
readable reason code (PRD BAB III).

Run:  uvicorn ml_service.main:app --host 127.0.0.1 --port 9000
"""
from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.ai.face_service import FaceRecognitionError, FaceRecognitionService
from app.ai.image_utils import decode_base64_image
from app.config import settings
from ml_service.security import face_rate_limiter, require_service_token

logger = logging.getLogger(__name__)

app = FastAPI(title="Monitoring PKL — Face ML Service", version="0.1.0")
face_service = FaceRecognitionService()


class FaceImageRequest(BaseModel):
    image_base64: str = Field(min_length=32)


class RegisterRequest(BaseModel):
    # Accept a single frame (image_base64) or several samples (images_base64).
    image_base64: str | None = None
    images_base64: list[str] | None = None
    user_id: int
    include_thumbnail: bool = False


class VerifyRequest(FaceImageRequest):
    embedding: list[float]
    threshold: float | None = None


def _rate_limit(request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    if not face_rate_limiter.allow(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Terlalu banyak permintaan ke layanan wajah. Coba lagi sebentar.",
        )


def _decode_or_400(image_base64: str) -> bytes:
    if len(image_base64) > settings.face_max_image_bytes:
        raise HTTPException(
            status_code=413,  # Content Too Large (constant name varies across Starlette versions)
            detail="Ukuran gambar melebihi batas yang diizinkan.",
        )
    try:
        return decode_base64_image(image_base64)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _face_error(exc: FaceRecognitionError) -> HTTPException:
    """Surface a fail-closed face error with its reason code to the caller."""
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=str(exc),
        headers={"X-Reason-Code": getattr(exc, "reason_code", "face_error")},
    )


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "model_ready": face_service.is_ready(), "engine": face_service.name}


@app.get("/model/status")
def model_status(_: None = Depends(require_service_token)) -> dict[str, object]:
    return {
        "engine": face_service.name,
        "ready": face_service.is_ready(),
        "threshold": settings.face_verify_threshold,
        "liveness_min_laplacian": settings.face_liveness_min_laplacian,
    }


@app.post("/face/liveness")
def liveness(
    payload: FaceImageRequest,
    _token: None = Depends(require_service_token),
    _limit: None = Depends(_rate_limit),
) -> dict[str, object]:
    return face_service.check_liveness(_decode_or_400(payload.image_base64))


@app.post("/face/register")
def register(
    payload: RegisterRequest,
    _token: None = Depends(require_service_token),
    _limit: None = Depends(_rate_limit),
) -> dict[str, object]:
    raw_images = payload.images_base64 or ([payload.image_base64] if payload.image_base64 else [])
    raw_images = [img for img in raw_images if img]
    if not raw_images:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Tidak ada sampel gambar yang dikirim."
        )
    images = [_decode_or_400(img) for img in raw_images]
    try:
        if len(images) > 1:
            result = face_service.register_embedding_multi(images, payload.user_id)
        else:
            result = face_service.register_embedding(images[0], payload.user_id)
    except FaceRecognitionError as exc:
        raise _face_error(exc) from exc
    if not payload.include_thumbnail:
        result = {key: value for key, value in result.items() if key != "thumbnail"}
    return result


@app.post("/face/verify")
def verify(
    payload: VerifyRequest,
    _token: None = Depends(require_service_token),
    _limit: None = Depends(_rate_limit),
) -> dict[str, object]:
    try:
        return face_service.verify_embedding(
            _decode_or_400(payload.image_base64),
            payload.embedding,
            payload.threshold,
        )
    except FaceRecognitionError as exc:
        raise _face_error(exc) from exc
