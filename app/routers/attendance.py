from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.attendance import Attendance
from app.models.user import User
from app.routers.web import FacePayload, verify_face
from app.security.session import require_user
from app.services.activity import log_activity
from app.services.audit import log_admin_action

router = APIRouter(prefix="/api/attendance", tags=["attendance"])


class ManualAttendanceRequest(BaseModel):
    user_id: int
    status: str = Field(default="hadir")
    alasan: Optional[str] = Field(default=None, max_length=500)


class AttendanceCheckinRequest(BaseModel):
    image_base64: str = Field(min_length=32, description="Tangkapan frame wajah kamera (base64)")
    latitude: float = Field(ge=-90, le=90, description="Latitude GPS")
    longitude: float = Field(ge=-180, le=180, description="Longitude GPS")
    accuracy_m: float = Field(ge=0, description="Akurasi sinyal GPS perangkat (meter)")


class AttendanceCheckoutRequest(BaseModel):
    image_base64: str = Field(min_length=32, description="Tangkapan frame wajah kamera (base64)")
    latitude: float = Field(ge=-90, le=90, description="Latitude GPS")
    longitude: float = Field(ge=-180, le=180, description="Longitude GPS")
    accuracy_m: float = Field(ge=0, description="Akurasi sinyal GPS perangkat (meter)")
    alasan: Optional[str] = Field(default="", max_length=500, description="Alasan jika pulang sebelum jam kepulangan")


def get_request_user(request: Request, db: Session, authorization: str | None = Header(default=None)) -> User:
    return require_user(request, db, authorization)


@router.post("/checkin")
def checkin(
    payload: AttendanceCheckinRequest,
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    """Check-in mandiri peserta dengan verifikasi wajah biometrik dan geofence GPS."""
    user = get_request_user(request, db, authorization)
    if user.role != "peserta":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya peserta PKL yang dapat melakukan check-in mandiri.",
        )

    face_payload = FacePayload(
        image_base64=payload.image_base64,
        action="checkin",
        latitude=payload.latitude,
        longitude=payload.longitude,
        accuracy_m=payload.accuracy_m,
    )
    return verify_face(payload=face_payload, request=request, db=db)


@router.post("/checkout")
def checkout(
    payload: AttendanceCheckoutRequest,
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    """Check-out mandiri peserta dengan verifikasi wajah biometrik dan geofence GPS."""
    user = get_request_user(request, db, authorization)
    if user.role != "peserta":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya peserta PKL yang dapat melakukan check-out mandiri.",
        )

    face_payload = FacePayload(
        image_base64=payload.image_base64,
        action="checkout",
        alasan=payload.alasan or "",
        latitude=payload.latitude,
        longitude=payload.longitude,
        accuracy_m=payload.accuracy_m,
    )
    return verify_face(payload=face_payload, request=request, db=db)


@router.get("/history")
def history(
    request: Request,
    user_id: int | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> list[dict[str, object]]:
    """Riwayat absensi dengan isolasi role (peserta hanya miliknya, admin/pembimbing fleksibel)."""
    current_user = get_request_user(request, db, authorization)

    query = db.query(Attendance)
    if current_user.role not in {"admin", "pembimbing"}:
        query = query.filter(Attendance.user_id == current_user.id)
    elif user_id is not None:
        query = query.filter(Attendance.user_id == user_id)

    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(Attendance.attendance_date >= start_dt)
        except ValueError:
            pass

    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(Attendance.attendance_date < end_dt)
        except ValueError:
            pass

    rows = query.order_by(Attendance.id.desc()).limit(limit).all()
    return [
        {
            "id": row.id,
            "user_id": row.user_id,
            "status": row.status,
            "attendance_date": row.attendance_date.isoformat() if row.attendance_date else None,
            "check_in_time": row.check_in_time.isoformat() if row.check_in_time else None,
            "check_out_time": row.check_out_time.isoformat() if row.check_out_time else None,
            "confidence_score": row.confidence_score,
            "latitude": row.latitude,
            "longitude": row.longitude,
            "distance_from_office_m": row.distance_from_office_m,
            "check_out_latitude": row.check_out_latitude,
            "check_out_longitude": row.check_out_longitude,
            "check_out_distance_m": row.check_out_distance_m,
            "location_review_status": row.location_review_status,
            "requires_location_review": row.requires_location_review,
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
    """Absensi manual oleh Admin atau Pembimbing dengan pencegahan duplikasi harian."""
    requester = get_request_user(request, db, authorization)
    if requester.role not in {"admin", "pembimbing"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya admin atau pembimbing yang dapat mencatat absensi manual.",
        )

    target_user = db.query(User).filter(User.id == payload.user_id, User.role == "peserta", User.is_active == True).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Peserta aktif tidak ditemukan.")

    allowed_status = {"hadir", "terlambat", "izin", "sakit", "alpa"}
    status_val = payload.status.lower().strip()
    if status_val not in allowed_status:
        raise HTTPException(
            status_code=400,
            detail=f"Status tidak valid. Pilihan: {', '.join(sorted(allowed_status))}",
        )

    now = datetime.now()
    start_of_day = datetime.combine(now.date(), time.min)
    end_of_day = datetime.combine(now.date() + timedelta(days=1), time.min)

    existing = (
        db.query(Attendance)
        .filter(
            Attendance.user_id == target_user.id,
            Attendance.attendance_date >= start_of_day,
            Attendance.attendance_date < end_of_day,
        )
        .first()
    )

    if existing:
        existing.status = status_val
        if existing.check_in_time is None and status_val in {"hadir", "terlambat"}:
            existing.check_in_time = now
        db.commit()
        db.refresh(existing)
        attendance = existing
        action_desc = "diperbarui"
    else:
        attendance = Attendance(
            user_id=target_user.id,
            attendance_date=now,
            check_in_time=now if status_val in {"hadir", "terlambat"} else None,
            status=status_val,
        )
        db.add(attendance)
        db.commit()
        db.refresh(attendance)
        action_desc = "dibuat"

    client_ip = request.client.host if request.client else None
    log_activity(
        db,
        requester.id,
        "manual_attendance",
        f"Absensi manual {target_user.username} {action_desc} dengan status '{status_val}'.",
        ip=client_ip,
    )
    if requester.role == "admin":
        log_admin_action(
            db,
            requester.id,
            "manual_attendance",
            target_user.id,
            f"Absensi manual status={status_val}",
            ip=client_ip,
        )
        db.commit()

    return {
        "message": f"Absensi manual berhasil {action_desc}.",
        "attendance_id": attendance.id,
        "status": attendance.status,
    }
