from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.attendance import Attendance
from app.models.user import User
from app.authentication.jwt_handler import verify_token

router = APIRouter(prefix="/attendance", tags=["attendance"])


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
def history(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    rows = db.query(Attendance).all()
    return [{"id": row.id, "user_id": row.user_id, "status": row.status} for row in rows]
