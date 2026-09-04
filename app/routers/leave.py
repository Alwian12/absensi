"""Routes for leave requests and activity log."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.attendance import Attendance
from app.models.activity_log import ActivityLog
from app.models.leave_request import LeaveRequest
from app.models.notification import Notification
from app.models.user import User
from app.routers.web import get_current_user, render_with_user
from app.services.activity import log_activity
from app.services.notifications import push_notification, push_to_role

router = APIRouter(tags=["leave"])
templates = Jinja2Templates(directory="app/templates")


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/leave")
def leave_page(request: Request, db: Session = Depends(get_db)) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    can_manage = current_user.role in {"admin", "pembimbing"}
    if can_manage:
        leaves = db.query(LeaveRequest).order_by(LeaveRequest.id.desc()).limit(200).all()
    else:
        leaves = db.query(LeaveRequest).filter(
            LeaveRequest.user_id == current_user.id
        ).order_by(LeaveRequest.id.desc()).all()

    return render_with_user(request, "leave.html", {"leaves": leaves, "can_manage": can_manage}, current_user)


@router.post("/leave")
def submit_leave(
    request: Request,
    tanggal: str = Form(...),
    jenis: str = Form("izin"),
    keterangan: str = Form(...),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role != "peserta":
        return RedirectResponse("/leave", status_code=status.HTTP_303_SEE_OTHER)

    try:
        tanggal_dt = datetime.strptime(tanggal, "%Y-%m-%d")
    except ValueError:
        return RedirectResponse("/leave?error=Format tanggal tidak valid.", status_code=status.HTTP_303_SEE_OTHER)

    if tanggal_dt.date() < date.today():
        return RedirectResponse("/leave?error=Izin hanya dapat diajukan untuk hari ini atau tanggal mendatang.", status_code=status.HTTP_303_SEE_OTHER)

    if jenis not in {"izin", "sakit"}:
        return RedirectResponse("/leave?error=Jenis permohonan tidak valid.", status_code=status.HTTP_303_SEE_OTHER)

    leave = LeaveRequest(user_id=current_user.id, tanggal=tanggal_dt, jenis=jenis, keterangan=keterangan.strip())
    db.add(leave)
    log_activity(db, current_user.id, "submit_leave", f"Izin tanggal {tanggal}: {keterangan[:60]}")
    push_to_role(db, "pembimbing", f"{current_user.username} mengajukan izin tanggal {tanggal}.", "info")
    push_to_role(db, "admin", f"{current_user.username} mengajukan izin tanggal {tanggal}.", "info")
    db.commit()
    return RedirectResponse("/leave?success=Permohonan izin berhasil diajukan.", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/leave/{leave_id}/review")
def review_leave(
    leave_id: int,
    request: Request,
    action: str = Form(...),
    catatan: str = Form(""),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user or current_user.role not in {"admin", "pembimbing"}:
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        return RedirectResponse("/leave?error=Permohonan tidak ditemukan.", status_code=status.HTTP_303_SEE_OTHER)

    if action not in {"approved", "rejected"}:
        return RedirectResponse("/leave", status_code=status.HTTP_303_SEE_OTHER)

    leave.status = action
    leave.reviewed_by = current_user.id
    leave.reviewed_at = datetime.now()
    leave.catatan_reviewer = catatan.strip()

    if action == "approved":
        day_start = datetime.combine(leave.tanggal.date(), datetime.min.time())
        day_end = day_start.replace(hour=23, minute=59, second=59)
        attendance = (
            db.query(Attendance)
            .filter(Attendance.user_id == leave.user_id)
            .filter(Attendance.attendance_date >= day_start, Attendance.attendance_date <= day_end)
            .order_by(Attendance.id.desc())
            .first()
        )
        if attendance and attendance.check_in_time is None:
            attendance.status = leave.jenis if leave.jenis in {"izin", "sakit"} else "izin"
        elif not attendance:
            db.add(Attendance(
                user_id=leave.user_id,
                attendance_date=day_start,
                status=leave.jenis if leave.jenis in {"izin", "sakit"} else "izin",
            ))

    label = "disetujui" if action == "approved" else "ditolak"
    push_notification(db, leave.user_id, f"Permohonan izin Anda {label} oleh {current_user.username}.", "success" if action == "approved" else "warning")
    log_activity(db, current_user.id, f"review_leave_{action}", f"Leave #{leave_id} milik user {leave.user_id}")
    db.commit()
    return RedirectResponse(f"/leave?success=Permohonan izin berhasil {label}.", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/activity-log")
def activity_log_page(request: Request, db: Session = Depends(get_db)) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    if current_user.role in {"admin", "pembimbing"}:
        logs = db.query(ActivityLog).order_by(ActivityLog.id.desc()).limit(300).all()
    else:
        logs = db.query(ActivityLog).filter(
            ActivityLog.user_id == current_user.id
        ).order_by(ActivityLog.id.desc()).limit(100).all()

    return render_with_user(request, "activity_log.html", {"logs": logs}, current_user)
