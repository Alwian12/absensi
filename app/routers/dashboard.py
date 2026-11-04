from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.attendance import Attendance
from app.models.journal import Journal
from app.models.user import User
from app.security.session import resolve_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(request: Request, db: Session = Depends(get_db)) -> dict[str, int]:
    if resolve_user(request, db) is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    total_users = db.query(User).count()
    total_attendance = db.query(Attendance).count()
    total_journals = db.query(Journal).count()
    return {
        "total_users": total_users,
        "total_attendance": total_attendance,
        "total_journals": total_journals,
    }
