"""Diagnostic: list registered routes and basic readiness checks (read-only)."""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as `python scripts/verify_routes.py` without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402


def main() -> None:
    paths = sorted({getattr(route, "path", "?") for route in app.routes})
    print(f"TOTAL_ROUTES={len(paths)}")
    api = [path for path in paths if path.startswith("/api/") or path.startswith("/auth/")]
    print(f"API_ROUTES={len(api)}")
    for path in paths:
        print(f"  {path}")


if __name__ == "__main__":
    main()
