from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import numpy as np
except ImportError:
    np = None

from PIL import Image

from app.config import settings

# Quality gates applied to a detected face *before* it is used for identity
# decisions. Conservative defaults; tighten only after validating against a
# labelled test set (PRD BAB IV/V).
MIN_FACE_PIXELS = 80          # minimum side (px) of the detected face box
MIN_SHARPNESS = 30.0          # Laplacian variance of the face crop
MIN_BRIGHTNESS = 35.0         # mean grayscale value
MAX_BRIGHTNESS = 230.0        # reject blown-out / overexposed frames
MAX_FACES_ALLOWED = 1         # ambiguous frames (multiple people) are rejected


class FaceRecognitionError(ValueError):
    """Fail-closed error for face processing.

    Subclasses ``ValueError`` so existing ``except ValueError`` handlers keep
    working, while carrying a machine-readable ``reason_code``.
    """

    def __init__(self, message: str, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class FaceRecognitionService:
    def __init__(self) -> None:
        self.name = "insightface"
        self._insight_app = None
        self._insight_attempted = False
        self._insight_ready = False

    def _ensure_insight_ready(self) -> None:
        if self._insight_attempted:
            return
        self._insight_attempted = True

        try:
            from insightface.app import FaceAnalysis

            app = FaceAnalysis(name="buffalo_l")
            app.prepare(ctx_id=-1, det_size=(640, 640))
            self._insight_app = app
            self._insight_ready = True
        except Exception:
            self._insight_app = None
            self._insight_ready = False

    def _decode_image(self, image_bytes: bytes) -> np.ndarray:
        if np is None:
            raise ValueError("Dependensi NumPy belum terpasang")
        try:
            image = Image.open(BytesIO(image_bytes)).convert("RGB")
        except Exception as exc:
            raise ValueError("Gambar tidak valid") from exc
        image_np = np.array(image, dtype=np.uint8)
        if image_np.size == 0:
            raise ValueError("Gambar tidak valid")
        if cv2 is not None and hasattr(cv2, "cvtColor") and hasattr(cv2, "COLOR_RGB2BGR"):
            try:
                return cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)
            except Exception:
                return image_np
        return image_np

    def is_ready(self) -> bool:
        """True when the real embedding model is loaded (else the service is fail-closed)."""
        self._ensure_insight_ready()
        return self._insight_ready

    def _select_face(self, faces: list) -> Any:
        return max(
            faces,
            key=lambda item: float((item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1])),
        )

    def _face_quality(self, image_bgr: np.ndarray, bbox: Any) -> dict[str, Any]:
        """Evaluate size / sharpness / brightness of a detected face box."""
        x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
        x1, y1 = max(0, x1), max(0, y1)
        width, height = x2 - x1, y2 - y1
        if width < MIN_FACE_PIXELS or height < MIN_FACE_PIXELS:
            return {
                "ok": False,
                "reason_code": "face_too_small",
                "message": "Wajah terlalu kecil atau terlalu jauh. Dekatkan wajah ke kamera lalu coba lagi.",
            }

        if cv2 is None or np is None:
            return {"ok": True, "sharpness": None, "brightness": None}

        crop = image_bgr[y1:y2, x1:x2]
        if crop.size == 0:
            return {
                "ok": False,
                "reason_code": "face_crop_empty",
                "message": "Area wajah tidak terbaca. Ulangi dengan posisi wajah yang jelas.",
            }

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())

        if sharpness < MIN_SHARPNESS:
            return {
                "ok": False,
                "reason_code": "face_blurry",
                "sharpness": round(sharpness, 2),
                "message": "Gambar wajah buram/kurang fokus. Tahan perangkat stabil lalu coba lagi.",
            }
        if brightness < MIN_BRIGHTNESS or brightness > MAX_BRIGHTNESS:
            return {
                "ok": False,
                "reason_code": "face_bad_lighting",
                "brightness": round(brightness, 2),
                "message": "Pencahayaan wajah kurang atau tidak merata. Cari cahaya yang lebih baik.",
            }

        return {
            "ok": True,
            "sharpness": round(sharpness, 2),
            "brightness": round(brightness, 2),
            "face_px": min(width, height),
        }

    def _preview_crop(self, image_bgr: np.ndarray) -> np.ndarray:
        """Best-effort face crop for the UI preview only (never used for matching)."""
        self._ensure_insight_ready()
        if self._insight_ready and self._insight_app is not None:
            faces = self._insight_app.get(image_bgr)
            if faces:
                x1, y1, x2, y2 = [int(v) for v in self._select_face(faces).bbox[:4]]
                crop = image_bgr[max(0, y1):y2, max(0, x1):x2]
                if crop.size:
                    return crop

        # Center-crop fallback is acceptable *here only*: the preview is cosmetic
        # and never influences a verification decision.
        h, w = image_bgr.shape[:2]
        crop_h, crop_w = int(h * 0.7), int(w * 0.7)
        start_y, start_x = max(0, (h - crop_h) // 2), max(0, (w - crop_w) // 2)
        crop = image_bgr[start_y:start_y + crop_h, start_x:start_x + crop_w]
        if crop.size == 0:
            raise FaceRecognitionError("Gagal mengambil area wajah", "crop_failed")
        return crop

    def _faces_inside_guide_circle(self, image_bgr: np.ndarray, faces: list) -> list:
        """Filter detected faces to those whose center falls inside the central oval/circle guide.

        This prevents bystanders in the background (outside the camera guide ring)
        from triggering a false `multiple_faces` error or being picked up accidentally.
        """
        if not faces or image_bgr is None or len(image_bgr.shape) < 2:
            return faces
        h, w = image_bgr.shape[:2]
        if h <= 0 or w <= 0:
            return faces

        cx_img = w / 2.0
        cy_img = h / 2.0
        # Normalized ellipse radii matching the oval guide in the camera preview (~38% width, ~42% height)
        rx = w * 0.38
        ry = h * 0.42

        inside = []
        for face in faces:
            x1, y1, x2, y2 = [float(v) for v in face.bbox[:4]]
            fcx = (x1 + x2) / 2.0
            fcy = (y1 + y2) / 2.0
            norm_dist = ((fcx - cx_img) / max(1.0, rx)) ** 2 + ((fcy - cy_img) / max(1.0, ry)) ** 2
            if norm_dist <= 1.0:
                inside.append(face)
        return inside

    def extract_embedding(self, image_bytes: bytes) -> dict[str, Any]:
        """Detect the largest face inside the guide circle and return its normalized embedding.

        Fails closed: if the model is unavailable, no face is found inside the guide circle,
        the frame has multiple faces inside the circle, or the face fails the quality gate,
        a ``FaceRecognitionError`` is raised — never a fallback match (audit findings F-11/F-12).
        """
        image = self._decode_image(image_bytes)
        self._ensure_insight_ready()
        if not (self._insight_ready and self._insight_app is not None):
            raise FaceRecognitionError(
                "Layanan pengenalan wajah belum siap di server. Hubungi administrator.",
                "model_unavailable",
            )

        raw_faces = self._insight_app.get(image)
        if not raw_faces:
            raise FaceRecognitionError(
                "Wajah tidak terdeteksi. Pastikan wajah berada di dalam lingkaran panduan kamera.", "no_face"
            )

        faces = self._faces_inside_guide_circle(image, raw_faces)
        if not faces:
            raise FaceRecognitionError(
                "Wajah terdeteksi di luar lingkaran panduan. Posisikan wajah tepat di tengah lingkaran kamera.",
                "no_face",
            )
        if len(faces) > MAX_FACES_ALLOWED:
            raise FaceRecognitionError(
                "Terdeteksi lebih dari satu wajah di dalam lingkaran panduan. Pastikan hanya wajah Anda di dalam lingkaran.",
                "multiple_faces",
            )

        selected_face = self._select_face(faces)
        quality = self._face_quality(image, selected_face.bbox)
        if not quality.get("ok"):
            raise FaceRecognitionError(
                quality.get("message", "Kualitas wajah belum cukup."),
                quality.get("reason_code", "low_quality"),
            )

        embedding = np.asarray(selected_face.embedding, dtype=np.float32)
        norm = np.linalg.norm(embedding)
        if norm == 0:
            raise FaceRecognitionError(
                "Embedding wajah kosong. Ulangi registrasi dengan posisi wajah lebih jelas.",
                "empty_embedding",
            )
        embedding = embedding / norm

        return {
            "embedding": embedding.tolist(),
            "engine": "insightface",
            "dim": int(embedding.shape[0]),
            "quality": quality,
            "faces_detected": len(faces),
        }

    def register_embedding(self, image_bytes: bytes, user_id: int) -> dict[str, Any]:
        payload = self.extract_embedding(image_bytes)
        thumbnail = self.extract_face_thumbnail(image_bytes)
        return {
            "user_id": user_id,
            "status": "registered",
            "engine": payload["engine"],
            "dim": payload["dim"],
            "embedding": payload["embedding"],
            "quality": payload.get("quality"),
            "thumbnail": thumbnail,
            "message": "Embedding wajah berhasil diproses.",
        }

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denominator == 0:
            return 0.0
        return float(np.dot(a, b) / denominator)

    def register_embedding_multi(self, images: list[bytes], user_id: int) -> dict[str, Any]:
        """Register a template from several quality-checked, mutually consistent samples.

        Rejects registration unless at least ``face_register_min_samples`` samples
        pass the quality gate AND their pairwise similarity stays above
        ``face_embedding_consistency_min`` (audit finding F-16, PRD BAB V/5.2).
        The stored template is the normalized mean embedding.
        """
        if len(images) < settings.face_register_min_samples:
            raise FaceRecognitionError(
                f"Perlu minimal {settings.face_register_min_samples} sampel wajah berkualitas. "
                "Ulangi registrasi dan tahan posisi wajah di depan kamera.",
                "too_few_samples",
            )
        if len(images) > settings.face_register_max_samples:
            images = images[: settings.face_register_max_samples]

        embeddings: list[np.ndarray] = []
        best_index = 0
        best_score = -1.0
        for index, image_bytes in enumerate(images):
            payload = self.extract_embedding(image_bytes)  # fail-closed on low quality
            embeddings.append(np.asarray(payload["embedding"], dtype=np.float32))
            score = float((payload.get("quality") or {}).get("sharpness") or 0.0)
            if score > best_score:
                best_score = score
                best_index = index

        similarities = [
            self._cosine_similarity(embeddings[i], embeddings[j])
            for i in range(len(embeddings))
            for j in range(i + 1, len(embeddings))
        ]
        min_pair_similarity = min(similarities) if similarities else 1.0
        if min_pair_similarity < settings.face_embedding_consistency_min:
            raise FaceRecognitionError(
                "Sampel wajah tidak konsisten (kemungkinan bergerak atau berbeda orang). "
                "Ulangi registrasi dengan posisi dan pencahayaan yang stabil.",
                "inconsistent_samples",
            )

        mean_embedding = np.mean(np.stack(embeddings), axis=0)
        norm = float(np.linalg.norm(mean_embedding))
        if norm == 0:
            raise FaceRecognitionError(
                "Gagal menyusun template wajah. Ulangi registrasi.", "empty_embedding"
            )
        mean_embedding = mean_embedding / norm

        thumbnail = self.extract_face_thumbnail(images[best_index])
        return {
            "user_id": user_id,
            "status": "registered",
            "engine": "insightface",
            "dim": int(mean_embedding.shape[0]),
            "embedding": mean_embedding.tolist(),
            "quality": {
                "samples_used": len(embeddings),
                "min_pair_similarity": round(min_pair_similarity, 4),
            },
            "thumbnail": thumbnail,
            "message": f"Template wajah dibuat dari {len(embeddings)} sampel.",
        }

    def extract_face_thumbnail(self, image_bytes: bytes, size: int = 160) -> str | None:
        """Small JPEG data URL of the detected face crop.

        UI-only confirmation image; never used for matching. It is still a
        biometric image, so the caller stores it encrypted (audit finding F-18).
        """
        try:
            image = self._decode_image(image_bytes)
            face = self._preview_crop(image)
            if cv2 is not None and hasattr(cv2, "resize") and hasattr(cv2, "cvtColor"):
                resized = cv2.resize(face, (size, size), interpolation=cv2.INTER_AREA)
                rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb)
            else:
                pil_img = Image.fromarray(face).convert("RGB").resize((size, size))
            buffer = BytesIO()
            pil_img.save(buffer, format="JPEG", quality=78)
            encoded = base64.b64encode(buffer.getvalue()).decode()
            return f"data:image/jpeg;base64,{encoded}"
        except Exception:
            return None

    def check_liveness(self, image_bytes: bytes) -> dict[str, Any]:
        """Passive anti-spoof via Laplacian texture variance.

        Fail-closed: any error or missing dependency rejects the frame instead of
        silently passing it (audit finding F-13). Printed/screen photos score lower.
        """
        if cv2 is None or np is None:
            return {"passed": False, "score": -1.0, "method": "unavailable"}
        try:
            image = self._decode_image(image_bytes)
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            return {
                "passed": lap_var > settings.face_liveness_min_laplacian,
                "score": round(lap_var, 2),
                "method": "laplacian",
            }
        except Exception:
            return {"passed": False, "score": -1.0, "method": "error"}

    def verify_embedding(
        self,
        image_bytes: bytes,
        stored_embedding: list[float],
        threshold: float | None = None,
    ) -> dict[str, Any]:
        """Compare a probe image against a stored template (1:1 verification).

        The score is a cosine similarity in ``[-1, 1]``. It is NOT a probability
        that the identity is correct (audit finding F-15), so it must not be shown
        as a percentage of certainty. The acceptance threshold comes from
        configuration and must be validated with measured FAR/FRR (PRD BAB IV/4.4).
        """
        active_threshold = settings.face_verify_threshold if threshold is None else threshold
        payload = self.extract_embedding(image_bytes)
        current = np.asarray(payload["embedding"], dtype=np.float32)
        reference = np.asarray(stored_embedding, dtype=np.float32)

        if current.shape[0] == 0 or reference.shape[0] == 0:
            raise FaceRecognitionError("Embedding tidak valid", "invalid_embedding")
        if current.shape[0] != reference.shape[0]:
            raise FaceRecognitionError(
                "Format data wajah berbeda. Silakan registrasi ulang wajah Anda.",
                "embedding_dim_mismatch",
            )

        current_norm = np.linalg.norm(current)
        ref_norm = np.linalg.norm(reference)
        if current_norm == 0 or ref_norm == 0:
            raise FaceRecognitionError("Embedding kosong", "empty_embedding")

        similarity = float(np.dot(current, reference) / (current_norm * ref_norm))
        matched = similarity >= active_threshold

        return {
            "status": "verified" if matched else "rejected",
            "matched": matched,
            "similarity": round(similarity, 4),
            "confidence": round(similarity, 4),  # legacy alias = similarity, not a certainty
            "threshold": active_threshold,
            "engine": payload["engine"],
            "quality": payload.get("quality"),
            "reason_code": "match" if matched else "below_threshold",
            "message": "Verifikasi wajah berhasil." if matched else "Wajah tidak cocok dengan data terdaftar.",
        }
