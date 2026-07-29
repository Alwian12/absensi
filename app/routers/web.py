from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.authentication.jwt_handler import hash_password, verify_password
from app.database import SessionLocal
from app.models.attendance import Attendance
from app.models.journal import Journal
from app.models.participant import Participant
from app.models.user import User

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="app/templates")


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/login")
def login_page(request: Request) -> object:
    return templates.TemplateResponse(request, "login.html", {"request": request})


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> object:
    user = db.query(User).filter(User.email == email).first()
    if user and verify_password(password, user.password_hash):
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"request": request, "error": "Email atau password salah."},
    )


@router.get("/register")
def register_page(request: Request) -> object:
    return templates.TemplateResponse(request, "register.html", {"request": request})


@router.post("/register")
def register_submit(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> object:
    existing = db.query(User).filter((User.email == email) | (User.username == username)).first()
    if existing:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"request": request, "error": "Username atau email sudah terdaftar."},
        )

    user = User(username=username, email=email, password_hash=hash_password(password), role="peserta")
    db.add(user)
    db.commit()
    db.refresh(user)
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/dashboard")
def dashboard_page(request: Request, db: Session = Depends(get_db)) -> object:
    total_users = db.query(User).count()
    total_participants = db.query(Participant).count()
    total_attendance = db.query(Attendance).count()
    total_journal = db.query(Journal).count()
    recent_attendance = db.query(Attendance).order_by(Attendance.id.desc()).limit(5).all()
    recent_journal = db.query(Journal).order_by(Journal.id.desc()).limit(5).all()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "total_users": total_users,
            "total_participants": total_participants,
            "total_attendance": total_attendance,
            "total_journal": total_journal,
            "recent_attendance": recent_attendance,
            "recent_journal": recent_journal,
        },
    )


@router.get("/participants")
def participants_page(request: Request, db: Session = Depends(get_db)) -> object:
    participants = db.query(Participant).all()
    users = db.query(User).filter(User.role == "peserta").all()
    return templates.TemplateResponse(
        request,
        "participants.html",
        {"request": request, "participants": participants, "users": users},
    )


@router.post("/participants")
def create_participant(
    request: Request,
    nama_lengkap: str = Form(...),
    jurusan: str = Form(...),
    instansi: str = Form(...),
    user_id: int = Form(...),
    db: Session = Depends(get_db),
) -> object:
    participant = Participant(user_id=user_id, nama_lengkap=nama_lengkap, jurusan=jurusan, instansi=instansi)
    db.add(participant)
    db.commit()
    return RedirectResponse("/participants", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/attendance")
def attendance_page(request: Request, db: Session = Depends(get_db)) -> object:
    attendance = db.query(Attendance).all()
    users = db.query(User).all()
    return templates.TemplateResponse(
        request,
        "attendance.html",
        {"request": request, "attendance": attendance, "users": users},
    )


@router.post("/attendance")
def create_attendance(
    request: Request,
    user_id: int = Form(...),
    status: str = Form(...),
    db: Session = Depends(get_db),
) -> object:
    attendance = Attendance(user_id=user_id, status=status)
    db.add(attendance)
    db.commit()
    return RedirectResponse("/attendance", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/journal")
def journal_page(request: Request, db: Session = Depends(get_db)) -> object:
    journals = db.query(Journal).all()
    users = db.query(User).all()
    return templates.TemplateResponse(
        request,
        "journal.html",
        {"request": request, "journals": journals, "users": users},
    )


@router.post("/journal")
def create_journal(
    request: Request,
    user_id: int = Form(...),
    kegiatan: str = Form(...),
    output: str = Form(""),
    db: Session = Depends(get_db),
) -> object:
    journal = Journal(user_id=user_id, kegiatan=kegiatan, output=output)
    db.add(journal)
    db.commit()
    return RedirectResponse("/journal", status_code=status.HTTP_303_SEE_OTHER)
