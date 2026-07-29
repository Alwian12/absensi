from typing import Any


class FaceRecognitionService:
    def __init__(self) -> None:
        self.name = "insightface"

    def register_embedding(self, image_bytes: bytes, user_id: int) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "status": "registered",
            "message": "Embedding wajah berhasil diproses (contoh placeholder).",
        }

    def verify_embedding(self, image_bytes: bytes, user_id: int) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "status": "verified",
            "confidence": 0.92,
            "message": "Verifikasi wajah berhasil (contoh placeholder).",
        }
