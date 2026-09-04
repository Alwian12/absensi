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


class FaceRecognitionService:
    def __init__(self) -> None:
        self.name = "insightface"
        self._detector = None
        self._insight_app = None
        self._insight_attempted = False
        self._insight_ready = False

        if cv2 is None or np is None:
            return

        try:
            self._detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        except Exception:
            self._detector = None

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

    def _detect_face(self, image_bgr: np.ndarray) -> np.ndarray:
        if cv2 is not None and self._detector is not None and hasattr(cv2, "cvtColor"):
            try:
                gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
                faces = self._detector.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(80, 80))
                if len(faces) > 0:
                    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                    face = image_bgr[y : y + h, x : x + w]
                    if face.size > 0:
                        return face
            except Exception:
                pass

        # Fallback center crop agar alur demo tetap bisa digunakan.
        h, w = image_bgr.shape[:2]
        crop_h = int(h * 0.7)
        crop_w = int(w * 0.7)
        start_y = max(0, (h - crop_h) // 2)
        start_x = max(0, (w - crop_w) // 2)
        face = image_bgr[start_y : start_y + crop_h, start_x : start_x + crop_w]
        if face.size == 0:
            raise ValueError("Gagal mengambil area wajah")
        return face

    def _extract_embedding(self, face_bgr: np.ndarray) -> tuple[np.ndarray, str]:
        self._ensure_insight_ready()
        if self._insight_ready and self._insight_app is not None:
            faces = self._insight_app.get(face_bgr)
            if faces:
                selected_face = max(
                    faces,
                    key=lambda item: float((item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1])),
                )
                vector = np.asarray(selected_face.embedding, dtype=np.float32)
                norm = np.linalg.norm(vector)
                if norm > 0:
                    vector = vector / norm
                return vector, "insightface"

        # Fallback embedding jika model InsightFace belum siap di environment.
        if cv2 is not None and hasattr(cv2, "resize") and hasattr(cv2, "cvtColor"):
            resized = cv2.resize(face_bgr, (64, 64), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        else:
            pil_img = Image.fromarray(face_bgr).convert("L").resize((64, 64))
            gray = np.asarray(pil_img, dtype=np.float32) / 255.0
        vector = gray.flatten()
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm
        return vector, "fallback-opencv"

    def extract_embedding(self, image_bytes: bytes) -> dict[str, Any]:
        image = self._decode_image(image_bytes)
        self._ensure_insight_ready()
        if self._insight_ready and self._insight_app is not None:
            faces = self._insight_app.get(image)
            if not faces:
                raise ValueError("Wajah tidak terdeteksi. Pastikan wajah terlihat jelas di kamera.")
            selected_face = max(
                faces,
                key=lambda item: float((item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1])),
            )
            embedding = np.asarray(selected_face.embedding, dtype=np.float32)
            norm = np.linalg.norm(embedding)
            if norm == 0:
                raise ValueError("Embedding wajah kosong. Ulangi registrasi dengan posisi wajah lebih jelas.")
            embedding = embedding / norm
            engine = "insightface"
        else:
            face = self._detect_face(image)
            embedding, engine = self._extract_embedding(face)
        return {
            "embedding": embedding.tolist(),
            "engine": engine,
            "dim": int(embedding.shape[0]),
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
            "thumbnail": thumbnail,
            "message": "Embedding wajah berhasil diproses.",
        }

    def extract_face_thumbnail(self, image_bytes: bytes, size: int = 160) -> str | None:
        """Small JPEG data URL of the detected face crop, for UI confirmation only (not used for matching)."""
        try:
            image = self._decode_image(image_bytes)
            face = self._detect_face(image)
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
        """Passive anti-spoof via Laplacian texture variance. Printed/screen photos score lower."""
        if cv2 is None or np is None:
            return {"passed": True, "score": -1.0, "method": "skipped"}
        try:
            image = self._decode_image(image_bytes)
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            return {"passed": lap_var > 15.0, "score": round(lap_var, 2), "method": "laplacian"}
        except Exception:
            return {"passed": True, "score": -1.0, "method": "error"}

    def verify_embedding(self, image_bytes: bytes, stored_embedding: list[float], threshold: float = 0.45) -> dict[str, Any]:
        payload = self.extract_embedding(image_bytes)
        current = np.asarray(payload["embedding"], dtype=np.float32)
        reference = np.asarray(stored_embedding, dtype=np.float32)

        if current.shape[0] == 0 or reference.shape[0] == 0:
            raise ValueError("Embedding tidak valid")
        if current.shape[0] != reference.shape[0]:
            raise ValueError("Format data wajah berbeda. Silakan registrasi ulang wajah Anda.")

        current_norm = np.linalg.norm(current)
        ref_norm = np.linalg.norm(reference)
        if current_norm == 0 or ref_norm == 0:
            raise ValueError("Embedding kosong")

        similarity = float(np.dot(current, reference) / (current_norm * ref_norm))
        confidence = max(0.0, min(1.0, (similarity + 1.0) / 2.0))
        matched = similarity >= threshold

        return {
            "status": "verified" if matched else "rejected",
            "matched": matched,
            "confidence": round(confidence, 4),
            "similarity": round(similarity, 4),
            "threshold": threshold,
            "engine": payload["engine"],
            "message": "Verifikasi wajah berhasil." if matched else "Wajah tidak cocok dengan data terdaftar.",
        }
