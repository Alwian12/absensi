"""Shared image decoding helpers for the face pipeline."""
from __future__ import annotations

import base64


def decode_base64_image(payload: str) -> bytes:
    """Decode a raw base64 string or a ``data:`` URL into bytes.

    Raises ``ValueError`` on malformed input so callers can map it to the right
    HTTP status (the web layer returns 400, the ML service returns 400 too).
    """
    encoded = payload.split(",", 1)[1] if "," in payload else payload
    try:
        return base64.b64decode(encoded)
    except Exception as exc:
        raise ValueError("Format gambar tidak valid") from exc


def encode_base64_image(image_bytes: bytes) -> str:
    """Encode raw image bytes to a base64 string (no data: prefix)."""
    return base64.b64encode(image_bytes).decode("ascii")
