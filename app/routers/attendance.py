from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.attendance import Attendance
from app.models.user import User
from app.authentication.jwt_handler import verify_token

router = APIRouter(prefix="/api/attendance", tags=["attendance"])


class ManualAttendanceRequest(BaseModel):
    user_id: int
    status: str = Field(default="hadir")


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_request_user(request: Request, db: Session, authorization: str | None = Header(default=None)) -> User:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = verify_token(token)
            user_id = int(payload["sub"])
            user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
            if user:
                return user
        except Exception:
            pass

    raw_user_id = request.cookies.get("user_id")
    if raw_user_id and raw_user_id.isdigit():
        user = db.query(User).filter(User.id == int(raw_user_id), User.is_active == True).first()
        if user:
            return user

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@router.post("/checkin")
def checkin(token: str, db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        payload = verify_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user_id = int(payload["sub"])
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    attendance = Attendance(user_id=user_id, status="hadir")
    db.add(attendance)
    db.commit()
    db.refresh(attendance)
    return {"message": "Check-in recorded", "attendance_id": attendance.id}


@router.get("/history")
def history(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> list[dict[str, object]]:
    user = get_request_user(request, db, authorization)

    query = db.query(Attendance)
    if user.role not in {"admin", "pembimbing"}:
        query = query.filter(Attendance.user_id == user.id)

    rows = query.order_by(Attendance.id.desc()).all()
    return [
        {
            "id": row.id,
            "user_id": row.user_id,
            "status": row.status,
            "check_in_time": row.check_in_time.isoformat() if row.check_in_time else None,
            "check_out_time": row.check_out_time.isoformat() if row.check_out_time else None,
            "confidence_score": row.confidence_score,
        }
        for row in rows
    ]


@router.post("/manual")
def create_manual_attendance(
    payload: ManualAttendanceRequest,
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    requester = get_request_user(request, db, authorization)
    if requester.role not in {"admin", "pembimbing"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    attendance = Attendance(
        user_id=payload.user_id,
        check_in_time=datetime.now(),
        status=payload.status,
    )
    db.add(attendance)
    db.commit()
    db.refresh(attendance)
    return {
        "message": "Manual attendance recorded",
        "attendance_id": attendance.id,
    }
