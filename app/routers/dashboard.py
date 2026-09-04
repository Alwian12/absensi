from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.attendance import Attendance
from app.models.journal import Journal
from app.models.user import User

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("")
def dashboard(db: Session = Depends(get_db)) -> dict[str, int]:
    total_users = db.query(User).count()
    total_attendance = db.query(Attendance).count()
    total_journals = db.query(Journal).count()
    return {
        "total_users": total_users,
        "total_attendance": total_attendance,
        "total_journals": total_journals,
    }
