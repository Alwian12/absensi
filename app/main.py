from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import inspect, text
from starlette.requests import Request
from contextlib import asynccontextmanager

from app.security.csrf import CSRFMiddleware, generate_csrf_token

from app.database import Base, engine, SessionLocal
from app.models import (
    ActivityLog,
    AdminAuditLog,
    Announcement,
    AppSetting,
    Assessment,
    Attendance,
    FaceEmbedding,
    FaceVerificationLog,
    Institution,
    Journal,
    LeaveRequest,
    Notification,
    Participant,
    Supervisor,
    User,
)
from app.routers.admin import router as admin_router
from app.routers.attendance import router as attendance_router
from app.routers.auth import router as auth_router
from app.routers.dashboard import router as dashboard_router
from app.routers.journal import router as journal_router
from app.routers.leave import router as leave_router
from app.routers.reports import router as reports_router
from app.routers.web import router as web_router

Base.metadata.create_all(bind=engine)


def patch_legacy_schema() -> None:
    inspector = inspect(engine)

    with engine.begin() as conn:
        journal_columns = {col["name"] for col in inspector.get_columns("jurnal")}
        if "signed_by_supervisor_id" not in journal_columns:
            conn.execute(text("ALTER TABLE jurnal ADD COLUMN signed_by_supervisor_id INTEGER NULL"))
        if "signed_at" not in journal_columns:
            conn.execute(text("ALTER TABLE jurnal ADD COLUMN signed_at DATETIME NULL"))
        if "signature_token" not in journal_columns:
            conn.execute(text("ALTER TABLE jurnal ADD COLUMN signature_token VARCHAR(255) NULL"))

        supervisor_columns = {col["name"] for col in inspector.get_columns("pembimbing")}
        if "nip" not in supervisor_columns:
            conn.execute(text("ALTER TABLE pembimbing ADD COLUMN nip VARCHAR(50) NULL"))
        if "jabatan" not in supervisor_columns:
            conn.execute(text("ALTER TABLE pembimbing ADD COLUMN jabatan VARCHAR(120) NULL"))

        instansi_columns = {col["name"] for col in inspector.get_columns("instansi")}
        if "office_latitude" not in instansi_columns:
            conn.execute(text("ALTER TABLE instansi ADD COLUMN office_latitude FLOAT NULL"))
        if "office_longitude" not in instansi_columns:
            conn.execute(text("ALTER TABLE instansi ADD COLUMN office_longitude FLOAT NULL"))
        if "office_radius_m" not in instansi_columns:
            conn.execute(text("ALTER TABLE instansi ADD COLUMN office_radius_m INTEGER NULL"))
        if "office_grace_m" not in instansi_columns:
            conn.execute(text("ALTER TABLE instansi ADD COLUMN office_grace_m INTEGER NULL"))
        if "office_max_accuracy_m" not in instansi_columns:
            conn.execute(text("ALTER TABLE instansi ADD COLUMN office_max_accuracy_m INTEGER NULL"))

        peserta_columns = {col["name"] for col in inspector.get_columns("peserta")}
        if "tanggal_mulai" not in peserta_columns:
            conn.execute(text("ALTER TABLE peserta ADD COLUMN tanggal_mulai DATETIME NULL"))
        if "tanggal_selesai" not in peserta_columns:
            conn.execute(text("ALTER TABLE peserta ADD COLUMN tanggal_selesai DATETIME NULL"))

        user_columns = {col["name"] for col in inspector.get_columns("users")}
        if "session_version" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1"))
        if "deleted_at" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN deleted_at DATETIME NULL"))

        absensi_columns = {col["name"] for col in inspector.get_columns("absensi")}
        if "alasan_pulang_cepat" not in absensi_columns:
            conn.execute(text("ALTER TABLE absensi ADD COLUMN alasan_pulang_cepat VARCHAR(500) NULL"))
        if "latitude" not in absensi_columns:
            conn.execute(text("ALTER TABLE absensi ADD COLUMN latitude FLOAT NULL"))
        if "longitude" not in absensi_columns:
            conn.execute(text("ALTER TABLE absensi ADD COLUMN longitude FLOAT NULL"))
        if "distance_from_office_m" not in absensi_columns:
            conn.execute(text("ALTER TABLE absensi ADD COLUMN distance_from_office_m FLOAT NULL"))
        if "requires_location_review" not in absensi_columns:
            conn.execute(text("ALTER TABLE absensi ADD COLUMN requires_location_review BOOLEAN NOT NULL DEFAULT 0"))
        if "location_review_reason" not in absensi_columns:
            conn.execute(text("ALTER TABLE absensi ADD COLUMN location_review_reason VARCHAR(30) NULL"))
        if "location_review_status" not in absensi_columns:
            conn.execute(text("ALTER TABLE absensi ADD COLUMN location_review_status VARCHAR(20) NOT NULL DEFAULT 'not_required'"))
        if "location_review_note" not in absensi_columns:
            conn.execute(text("ALTER TABLE absensi ADD COLUMN location_review_note VARCHAR(300) NULL"))
        if "location_reviewed_by_user_id" not in absensi_columns:
            conn.execute(text("ALTER TABLE absensi ADD COLUMN location_reviewed_by_user_id INTEGER NULL"))
        if "location_reviewed_at" not in absensi_columns:
            conn.execute(text("ALTER TABLE absensi ADD COLUMN location_reviewed_at DATETIME NULL"))

        leave_columns = {col["name"] for col in inspector.get_columns("permohonan_izin")}
        if "jenis" not in leave_columns:
            conn.execute(text("ALTER TABLE permohonan_izin ADD COLUMN jenis VARCHAR(20) NOT NULL DEFAULT 'izin'"))

        face_embeddings_columns = {col["name"] for col in inspector.get_columns("face_embeddings")}
        if "thumbnail_encrypted" not in face_embeddings_columns:
            conn.execute(text("ALTER TABLE face_embeddings ADD COLUMN thumbnail_encrypted MEDIUMTEXT NULL"))


patch_legacy_schema()


def seed_default_settings() -> None:
    from app.models.app_setting import AppSetting as _AS
    defaults = {
        "jam_masuk": "08:15",
        "jam_pulang": "16:00",
        "attendance_success_auto_hide_seconds": "9",
        "attendance_transition_style": "normal",
        "office_latitude": "",
        "office_longitude": "",
        "office_radius_m": "200",
        "office_grace_m": "15",
        "office_max_accuracy_m": "80",
    }
    db = SessionLocal()
    try:
        for key, val in defaults.items():
            if not db.query(_AS).filter(_AS.key == key).first():
                db.add(_AS(key=key, value=val))
        db.commit()
    finally:
        db.close()


seed_default_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Monitoring PKL", version="0.1.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CSRFMiddleware)
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Cache control middleware for static assets
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as _Response

class StaticCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/vendor/") or request.url.path.startswith("/static/icons/"):
            response.headers["Cache-Control"] = "public, max-age=604800, immutable"  # 7 days
        elif request.url.path.startswith("/static/"):
            # No long cache for app CSS/JS: they change frequently during active development.
            # Browser still revalidates cheaply via ETag/Last-Modified (304), so this isn't a full refetch.
            response.headers["Cache-Control"] = "no-cache"
        else:
            # Prevent browser back-cache showing authenticated pages after logout.
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(StaticCacheMiddleware)
app.include_router(auth_router)
app.include_router(attendance_router)
app.include_router(journal_router)
app.include_router(dashboard_router)
app.include_router(reports_router)
app.include_router(admin_router)
app.include_router(leave_router)
app.include_router(web_router)


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"request": request})


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
