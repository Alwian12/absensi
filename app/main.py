from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from contextlib import asynccontextmanager

from app.security.csrf import CSRFMiddleware, generate_csrf_token
from app.security.session import SESSION_COOKIE, read_session_token

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


def ensure_schema_columns() -> None:
    """Idempotently ensure newer columns exist on existing databases."""
    from sqlalchemy import inspect as _inspect, text as _text
    try:
        inspector = _inspect(engine)
        if "peserta" in inspector.get_table_names():
            cols = {c["name"] for c in inspector.get_columns("peserta")}
            if "bidang" not in cols:
                with engine.begin() as conn:
                    conn.execute(_text("ALTER TABLE peserta ADD COLUMN bidang VARCHAR(100) NULL"))
    except Exception:
        pass


ensure_schema_columns()


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


@app.get("/")
def read_root(request: Request) -> RedirectResponse:
    token = request.cookies.get(SESSION_COOKIE)
    if token and read_session_token(token):
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
