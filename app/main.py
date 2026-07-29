from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.database import Base, engine
from app.models import Attendance, Journal, Participant, Supervisor, User
from app.routers.admin import router as admin_router
from app.routers.attendance import router as attendance_router
from app.routers.auth import router as auth_router
from app.routers.dashboard import router as dashboard_router
from app.routers.journal import router as journal_router
from app.routers.web import router as web_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Monitoring PKL", version="0.1.0")
templates = Jinja2Templates(directory="app/templates")
app.include_router(auth_router)
app.include_router(attendance_router)
app.include_router(journal_router)
app.include_router(dashboard_router)
app.include_router(admin_router)
app.include_router(web_router)


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"request": request})


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
