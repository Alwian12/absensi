"""Frontend consistency guards (audit finding F-24).

The UI must not depend on external CDNs: government/office networks may block
them, and they add privacy + availability risk. All libraries and fonts are
vendored under ``app/static/vendor``.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app" / "templates"
VENDOR = ROOT / "app" / "static" / "vendor"

EXTERNAL_MARKERS = (
    "cdn.jsdelivr.net",
    "cdn.tailwindcss.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "unpkg.com",
    "cdnjs.cloudflare.com",
)


def test_templates_have_no_external_cdn_references() -> None:
    offenders: list[str] = []
    for template in TEMPLATES.glob("*.html"):
        text = template.read_text(encoding="utf-8", errors="replace")
        for marker in EXTERNAL_MARKERS:
            if marker in text:
                offenders.append(f"{template.name}: {marker}")
    assert not offenders, "External CDN references found: " + ", ".join(offenders)


@pytest.mark.parametrize(
    "relative_path",
    [
        "bootstrap.min.css",
        "bootstrap.bundle.min.js",
        "chart.umd.min.js",
        "lucide.min.js",
        "fonts.css",
    ],
)
def test_vendored_assets_exist(relative_path: str) -> None:
    assert (VENDOR / relative_path).is_file(), f"Missing vendored asset: {relative_path}"


def test_vendored_fonts_exist() -> None:
    fonts = list((VENDOR / "fonts").glob("*.woff2"))
    assert len(fonts) >= 5, "Expected the vendored Plus Jakarta Sans weights"


def test_fonts_css_uses_local_urls_only() -> None:
    css = (VENDOR / "fonts.css").read_text(encoding="utf-8")
    assert "http" not in css, "fonts.css must reference local files only"
    assert "/static/vendor/fonts/" in css


def test_vendored_font_is_served() -> None:
    response = TestClient(app).get("/static/vendor/fonts.css")
    assert response.status_code == 200
    assert "text/css" in response.headers.get("content-type", "")


def test_login_page_uses_local_assets_only() -> None:
    response = TestClient(app).get("/login")
    assert response.status_code == 200
    body = response.text
    assert "/static/vendor/fonts.css" in body
    for marker in EXTERNAL_MARKERS:
        assert marker not in body


def test_attendance_flow_defines_all_required_states() -> None:
    """PRD BAB VIII: the attendance flow must expose explicit user-facing states."""
    script = (ROOT / "app" / "static" / "js" / "attendance.js").read_text(encoding="utf-8")
    for stage in ("idle", "camera", "liveness", "processing", "no_face", "low_quality", "success", "error"):
        assert f"{stage}: {{" in script, f"Missing guide stage: {stage}"
    # Server reason codes must map to a helpful stage.
    assert "stageForError" in script


def test_vendored_assets_have_no_cdn_in_js() -> None:
    offenders: list[str] = []
    for script in (ROOT / "app" / "static" / "js").glob("*.js"):
        text = script.read_text(encoding="utf-8", errors="replace")
        for marker in EXTERNAL_MARKERS:
            if marker in text:
                offenders.append(f"{script.name}: {marker}")
    assert not offenders


def test_root_redirects_directly_to_login() -> None:
    response = TestClient(app).get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == "/login"
