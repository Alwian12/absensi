"""Password strength validation."""
import re


def validate_password(password: str) -> str | None:
    """Returns error message or None if OK."""
    if len(password) < 8:
        return "Password minimal 8 karakter."
    if not re.search(r"[A-Z]", password):
        return "Password harus mengandung huruf kapital."
    if not re.search(r"[0-9]", password):
        return "Password harus mengandung angka."
    return None
