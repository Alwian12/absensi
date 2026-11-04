"""HTTP client for the standalone face ML service (PRD BAB III).

The client exposes the same three methods used by the web layer
(``check_liveness``, ``register_embedding``, ``verify_embedding``) so the app can
switch between the in-process model and the remote service without touching the
routers.

Fail-closed: any transport/timeout/5xx error becomes a ``FaceRecognitionError``
with ``reason_code="service_unavailable"`` — the web layer maps that to HTTP 503
and the operator falls back to the supervised manual procedure. It never
silently accepts an attendance.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from app.ai.face_service import FaceRecognitionError
from app.ai.image_utils import encode_base64_image


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


# (url, body, headers, timeout) -> HttpResponse
Transport = Callable[[str, bytes, dict[str, str], float], HttpResponse]


def _http_post_json(url: str, body: bytes, headers: dict[str, str], timeout: float) -> HttpResponse:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(response.status, dict(response.headers), response.read())
    except urllib.error.HTTPError as exc:
        # urllib raises on 4xx/5xx; convert so the caller can inspect the status.
        return HttpResponse(exc.code, dict(exc.headers or {}), exc.read())


class FaceServiceClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._transport = transport or _http_post_json

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "X-Service-Token": self._token}

        try:
            result = self._transport(url, body, headers, self._timeout)
        except Exception as exc:
            raise FaceRecognitionError(
                "Layanan verifikasi wajah sedang tidak dapat diakses. Coba lagi, "
                "atau minta admin mencatat absensi secara manual (terawasi).",
                "service_unavailable",
            ) from exc

        if result.status >= 500:
            raise FaceRecognitionError(
                "Layanan verifikasi wajah mengalami gangguan. Coba lagi beberapa saat.",
                "service_unavailable",
            )
        if result.status >= 400:
            reason = _get_header(result.headers, "x-reason-code") or "face_error"
            raise FaceRecognitionError(_extract_detail(result.body), reason)
        return json.loads(result.body)

    def check_liveness(self, image_bytes: bytes) -> dict[str, Any]:
        return self._post("/face/liveness", {"image_base64": encode_base64_image(image_bytes)})

    def register_embedding(self, image_bytes: bytes, user_id: int) -> dict[str, Any]:
        return self.register_embedding_multi([image_bytes], user_id)

    def register_embedding_multi(self, images: list[bytes], user_id: int) -> dict[str, Any]:
        return self._post(
            "/face/register",
            {
                "images_base64": [encode_base64_image(image) for image in images],
                "user_id": user_id,
                "include_thumbnail": True,
            },
        )

    def verify_embedding(
        self,
        image_bytes: bytes,
        stored_embedding: list[float],
        threshold: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "image_base64": encode_base64_image(image_bytes),
            "embedding": stored_embedding,
        }
        if threshold is not None:
            payload["threshold"] = threshold
        return self._post("/face/verify", payload)


def _get_header(headers: dict[str, str], name: str) -> str | None:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def _extract_detail(body: bytes) -> str:
    try:
        detail = json.loads(body).get("detail")
        if isinstance(detail, str) and detail:
            return detail
    except Exception:
        pass
    return "Verifikasi wajah gagal diproses oleh layanan."
