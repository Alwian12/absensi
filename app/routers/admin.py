from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.assessment import Assessment
from app.models.institution import Institution
from app.models.participant import Participant
from app.models.supervisor import Supervisor
from app.models.user import User

router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/supervisors")
def supervisors_page(request: Request, db: Session = Depends(get_db)) -> object:
    supervisors = db.query(Supervisor).all()
    users = db.query(User).filter(User.role == "pembimbing").all()
    return templates.TemplateResponse(
        request,
        "supervisors.html",
        {"request": request, "supervisors": supervisors, "users": users},
    )


@router.post("/supervisors")
def create_supervisor(
    request: Request,
    nama_lengkap: str = Form(...),
    bidang: str = Form(...),
    user_id: int = Form(...),
    db: Session = Depends(get_db),
) -> object:
    supervisor = Supervisor(user_id=user_id, nama_lengkap=nama_lengkap, bidang=bidang)
    db.add(supervisor)
    db.commit()
    return RedirectResponse("/supervisors", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/institutions")
def institutions_page(request: Request, db: Session = Depends(get_db)) -> object:
    institutions = db.query(Institution).all()
    return templates.TemplateResponse(
        request,
        "institutions.html",
        {"request": request, "institutions": institutions},
    )


@router.post("/institutions")
def create_institution(
    request: Request,
    nama_instansi: str = Form(...),
    alamat: str = Form(...),
    kontak: str = Form(...),
    db: Session = Depends(get_db),
) -> object:
    institution = Institution(nama_instansi=nama_instansi, alamat=alamat, kontak=kontak)
    db.add(institution)
    db.commit()
    return RedirectResponse("/institutions", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/assessments")
def assessments_page(request: Request, db: Session = Depends(get_db)) -> object:
    assessments = db.query(Assessment).all()
    participants = db.query(Participant).all()
    return templates.TemplateResponse(
        request,
        "assessments.html",
        {"request": request, "assessments": assessments, "participants": participants},
    )


@router.post("/assessments")
def create_assessment(
    request: Request,
    user_id: int = Form(...),
    nilai: int = Form(...),
    catatan: str = Form(""),
    db: Session = Depends(get_db),
) -> object:
    assessment = Assessment(user_id=user_id, nilai=nilai, catatan=catatan)
    db.add(assessment)
    db.commit()
    return RedirectResponse("/assessments", status_code=status.HTTP_303_SEE_OTHER)
