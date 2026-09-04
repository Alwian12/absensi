from datetime import datetime, timedelta, time
import csv
from io import StringIO

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.authentication.jwt_handler import hash_password
from app.database import SessionLocal
from app.models.admin_audit_log import AdminAuditLog
from app.models.announcement import Announcement
from app.models.assessment import Assessment
from app.models.activity_log import ActivityLog
from app.models.attendance import Attendance
from app.models.face_verification_log import FaceVerificationLog
from app.models.face_embedding import FaceEmbedding
from app.models.institution import Institution
from app.models.journal import Journal
from app.models.leave_request import LeaveRequest
from app.models.notification import Notification
from app.models.participant import Participant
from app.models.supervisor import Supervisor
from app.models.user import User
from app.routers.web import get_current_user, render_with_user
from app.services.audit import log_admin_action
from app.services.activity import log_activity
from app.services.password_policy import validate_password

router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def parse_date_input(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    try:
        return datetime.strptime(raw_value, "%Y-%m-%d")
    except ValueError:
        return None


def parse_float_input(raw_value: str | None) -> float | None:
    if raw_value is None:
        return None
    txt = raw_value.strip()
    if not txt:
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def build_face_log_query(
    db: Session,
    result: str,
    action: str,
    from_dt: datetime | None,
    to_dt: datetime | None,
):
    query = db.query(FaceVerificationLog)

    if result == "success":
        query = query.filter(FaceVerificationLog.matched == True)
    elif result == "failed":
        query = query.filter(FaceVerificationLog.matched == False)
    elif result == "blocked":
        query = query.filter(FaceVerificationLog.attempt_blocked == True)

    if action in {"checkin", "checkout"}:
        query = query.filter(FaceVerificationLog.action == action)

    if from_dt is not None:
        query = query.filter(FaceVerificationLog.created_at >= from_dt)
    if to_dt is not None:
        query = query.filter(FaceVerificationLog.created_at <= to_dt)

    return query


@router.get("/supervisors")
def supervisors_page(request: Request, db: Session = Depends(get_db)) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    supervisors = db.query(Supervisor).all()
    all_pembimbing_users = db.query(User).filter(User.role == "pembimbing", User.is_active == True).all()
    linked_user_ids = {s.user_id for s in supervisors}
    users_without_profile = [u for u in all_pembimbing_users if u.id not in linked_user_ids]
    users = [u for u in all_pembimbing_users if u.id not in linked_user_ids]
    return render_with_user(
        request,
        "supervisors.html",
        {"supervisors": supervisors, "users": users, "users_without_profile": users_without_profile},
        current_user,
    )


@router.post("/supervisors")
def create_supervisor(
    request: Request,
    nama_lengkap: str = Form(...),
    nip: str = Form(""),
    jabatan: str = Form(""),
    bidang: str = Form(""),
    user_id: int = Form(...),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    supervisor = Supervisor(
        user_id=user_id,
        nama_lengkap=nama_lengkap,
        nip=nip.strip() or None,
        jabatan=jabatan.strip() or None,
        bidang=bidang.strip() or None,
    )
    db.add(supervisor)
    db.commit()
    return RedirectResponse("/supervisors", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/supervisors/create-account")
def create_supervisor_account(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    nama_lengkap: str = Form(...),
    nip: str = Form(""),
    jabatan: str = Form(""),
    bidang: str = Form(""),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user or current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    clean_username = username.strip()
    clean_email = email.strip().lower()
    duplicate = db.query(User).filter((User.username == clean_username) | (User.email == clean_email)).first()
    if duplicate:
        return RedirectResponse("/supervisors?error=Username atau email sudah digunakan.", status_code=status.HTTP_303_SEE_OTHER)

    password_error = validate_password(password.strip())
    if password_error:
        return RedirectResponse(f"/supervisors?error={password_error}", status_code=status.HTTP_303_SEE_OTHER)
    if not nama_lengkap.strip():
        return RedirectResponse("/supervisors?error=Nama lengkap wajib diisi.", status_code=status.HTTP_303_SEE_OTHER)

    new_user = User(
        username=clean_username,
        email=clean_email,
        password_hash=hash_password(password.strip()),
        role="pembimbing",
        is_active=True,
        session_version=1,
    )
    db.add(new_user)
    db.flush()
    db.add(
        Supervisor(
            user_id=new_user.id,
            nama_lengkap=nama_lengkap.strip(),
            nip=nip.strip() or None,
            jabatan=jabatan.strip() or None,
            bidang=bidang.strip() or None,
        )
    )
    log_admin_action(
        db,
        current_user.id,
        "create_supervisor_account",
        new_user.id,
        f"Buat akun pembimbing {new_user.username}",
        request.client.host if request.client else None,
    )
    db.commit()
    return RedirectResponse("/supervisors?success=Akun dan profil pembimbing berhasil dibuat.", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/password")
def admin_reset_user_password(
    user_id: int,
    request: Request,
    new_password: str = Form(...),
    redirect_to: str = Form("/dashboard"),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    clean_redirect = redirect_to if redirect_to in {"/participants", "/supervisors", "/dashboard"} else "/dashboard"
    password_candidate = new_password.strip()
    if len(password_candidate) < 6:
        return RedirectResponse(
            f"{clean_redirect}?error=Password minimal 6 karakter.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        return RedirectResponse(
            f"{clean_redirect}?error=Akun pengguna tidak ditemukan.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    target_user.password_hash = hash_password(password_candidate)
    log_admin_action(
        db,
        admin_user_id=current_user.id,
        action="reset_password",
        target_user_id=target_user.id,
        detail=f"Reset password akun {target_user.username}",
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return RedirectResponse(
        f"{clean_redirect}?success=Password akun {target_user.username} berhasil diperbarui.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/users/{user_id}/force-logout")
def admin_force_logout(
    user_id: int,
    request: Request,
    redirect_to: str = Form("/dashboard"),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    clean_redirect = redirect_to if redirect_to in {"/participants", "/supervisors", "/dashboard"} else "/dashboard"
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        return RedirectResponse(f"{clean_redirect}?error=Akun tidak ditemukan.", status_code=status.HTTP_303_SEE_OTHER)

    target_user.session_version = (target_user.session_version or 1) + 1
    log_admin_action(
        db,
        admin_user_id=current_user.id,
        action="force_logout",
        target_user_id=target_user.id,
        detail=f"Force logout semua sesi {target_user.username}",
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return RedirectResponse(
        f"{clean_redirect}?success=Semua sesi {target_user.username} telah dinonaktifkan.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/participants/{participant_id}/pkl-dates")
def set_pkl_dates(
    participant_id: int,
    request: Request,
    tanggal_mulai: str = Form(""),
    tanggal_selesai: str = Form(""),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    p = db.query(Participant).filter(Participant.id == participant_id).first()
    if not p:
        return RedirectResponse("/participants?error=Peserta tidak ditemukan.", status_code=status.HTTP_303_SEE_OTHER)

    p.tanggal_mulai = parse_date_input(tanggal_mulai)
    p.tanggal_selesai = parse_date_input(tanggal_selesai)
    db.commit()
    return RedirectResponse("/participants?success=Tanggal PKL berhasil disimpan.", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/participants/{participant_id}/edit")
def edit_participant(
    participant_id: int,
    request: Request,
    nama_lengkap: str = Form(...),
    jurusan: str = Form(""),
    instansi: str = Form(""),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user or current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    participant = db.query(Participant).filter(Participant.id == participant_id).first()
    if not participant:
        return RedirectResponse("/participants?error=Peserta tidak ditemukan.", status_code=status.HTTP_303_SEE_OTHER)

    participant.nama_lengkap = nama_lengkap.strip()
    participant.jurusan = jurusan.strip() or None
    participant.instansi = instansi.strip() or None
    log_activity(db, current_user.id, "edit_participant", f"Edit profil peserta {participant.nama_lengkap}")
    db.commit()
    return RedirectResponse("/participants?success=Profil peserta berhasil diperbarui.", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/participants/complete-profile/{user_id}")
def complete_participant_profile(
    user_id: int,
    request: Request,
    nama_lengkap: str = Form(...),
    jurusan: str = Form(""),
    instansi: str = Form(""),
    tanggal_mulai: str = Form(...),
    tanggal_selesai: str = Form(...),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user or current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    target_user = db.query(User).filter(User.id == user_id, User.role == "peserta", User.is_active == True).first()
    if not target_user:
        return RedirectResponse("/participants?error=Akun peserta tidak ditemukan atau tidak aktif.", status_code=status.HTTP_303_SEE_OTHER)
    if db.query(Participant).filter(Participant.user_id == user_id).first():
        return RedirectResponse("/participants?error=Akun peserta sudah memiliki profil.", status_code=status.HTTP_303_SEE_OTHER)

    try:
        mulai = parse_date_input(tanggal_mulai)
        selesai = parse_date_input(tanggal_selesai)
    except ValueError:
        mulai = None
        selesai = None
    if not mulai or not selesai:
        return RedirectResponse("/participants?error=Format tanggal PKL tidak valid.", status_code=status.HTTP_303_SEE_OTHER)
    if selesai < mulai:
        return RedirectResponse("/participants?error=Tanggal selesai PKL harus setelah tanggal mulai.", status_code=status.HTTP_303_SEE_OTHER)

    participant = Participant(
        user_id=user_id,
        nama_lengkap=nama_lengkap.strip(),
        jurusan=jurusan.strip() or None,
        instansi=instansi.strip() or None,
        tanggal_mulai=mulai,
        tanggal_selesai=selesai,
    )
    db.add(participant)
    log_activity(db, current_user.id, "complete_participant_profile", f"Lengkapi profil peserta {target_user.username}")
    db.commit()
    return RedirectResponse("/participants?success=Profil peserta berhasil dibuat.", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/supervisors/{supervisor_id}/edit")
def edit_supervisor(
    supervisor_id: int,
    request: Request,
    nama_lengkap: str = Form(...),
    nip: str = Form(""),
    jabatan: str = Form(""),
    bidang: str = Form(""),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user or current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    sv = db.query(Supervisor).filter(Supervisor.id == supervisor_id).first()
    if not sv:
        return RedirectResponse("/supervisors?error=Pembimbing tidak ditemukan.", status_code=status.HTTP_303_SEE_OTHER)

    sv.nama_lengkap = nama_lengkap.strip()
    sv.nip = nip.strip() or None
    sv.jabatan = jabatan.strip() or None
    sv.bidang = bidang.strip() or None
    db.commit()
    return RedirectResponse("/supervisors?success=Data pembimbing berhasil diperbarui.", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/journal/{journal_id}/comment")
def post_journal_comment(
    journal_id: int,
    request: Request,
    komentar: str = Form(...),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role not in {"admin", "pembimbing"}:
        return RedirectResponse("/journal", status_code=status.HTTP_303_SEE_OTHER)

    j = db.query(Journal).filter(Journal.id == journal_id).first()
    if not j:
        return RedirectResponse("/journal?error=Jurnal tidak ditemukan.", status_code=status.HTTP_303_SEE_OTHER)

    j.komentar = komentar.strip()[:500]
    db.commit()
    return RedirectResponse("/journal?success=Komentar berhasil disimpan.", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/announcements")
def announcements_page(request: Request, db: Session = Depends(get_db)) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    announcements = db.query(Announcement).order_by(Announcement.id.desc()).limit(100).all()
    return render_with_user(request, "announcements.html", {"announcements": announcements}, current_user)


@router.post("/announcements")
def create_announcement(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    db.add(Announcement(author_user_id=current_user.id, title=title.strip(), content=content.strip()))
    db.commit()
    return RedirectResponse("/announcements?success=Pengumuman berhasil diterbitkan.", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/announcements/{ann_id}/toggle")
def toggle_announcement(
    ann_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user or current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    ann = db.query(Announcement).filter(Announcement.id == ann_id).first()
    if ann:
        ann.is_active = not ann.is_active
        db.commit()
    return RedirectResponse("/announcements", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin-audit")
def admin_audit_page(request: Request, db: Session = Depends(get_db)) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    logs = db.query(AdminAuditLog).order_by(AdminAuditLog.id.desc()).limit(200).all()
    return render_with_user(request, "admin_audit.html", {"logs": logs}, current_user)


@router.post("/users/{user_id}/soft-delete")
def soft_delete_user(
    user_id: int,
    request: Request,
    redirect_to: str = Form("/participants"),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user or current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    if user_id == current_user.id:
        return RedirectResponse(f"{redirect_to}?error=Tidak dapat menghapus akun sendiri.", status_code=status.HTTP_303_SEE_OTHER)

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return RedirectResponse(f"{redirect_to}?error=Pengguna tidak ditemukan.", status_code=status.HTTP_303_SEE_OTHER)

    target.is_active = False
    target.deleted_at = datetime.now()
    target.session_version = (target.session_version or 1) + 1
    log_admin_action(db, current_user.id, "soft_delete_user", user_id,
                     f"Nonaktifkan {target.username}", request.client.host if request.client else None)
    db.commit()
    return RedirectResponse(f"{redirect_to}?success=Akun {target.username} berhasil dinonaktifkan.", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/delete")
def permanently_delete_user(
    user_id: int,
    request: Request,
    redirect_to: str = Form("/participants"),
    confirmation: str = Form(""),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user or current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    if user_id == current_user.id:
        return RedirectResponse(f"{redirect_to}?error=Tidak dapat menghapus akun sendiri.", status_code=status.HTTP_303_SEE_OTHER)
    if confirmation != "HAPUS":
        return RedirectResponse(f"{redirect_to}?error=Konfirmasi hapus tidak valid.", status_code=status.HTTP_303_SEE_OTHER)

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return RedirectResponse(f"{redirect_to}?error=Pengguna tidak ditemukan.", status_code=status.HTTP_303_SEE_OTHER)
    if target.role not in {"peserta", "pembimbing"}:
        return RedirectResponse(f"{redirect_to}?error=Hanya akun peserta atau pembimbing yang dapat dihapus.", status_code=status.HTTP_303_SEE_OTHER)

    target_name = target.username
    target_role = target.role
    db.query(Attendance).filter(Attendance.location_reviewed_by_user_id == user_id).update(
        {Attendance.location_reviewed_by_user_id: None}, synchronize_session=False
    )
    db.query(LeaveRequest).filter(LeaveRequest.reviewed_by == user_id).update(
        {LeaveRequest.reviewed_by: None}, synchronize_session=False
    )
    db.query(AdminAuditLog).filter(
        (AdminAuditLog.admin_user_id == user_id) | (AdminAuditLog.target_user_id == user_id)
    ).delete(synchronize_session=False)
    db.query(ActivityLog).filter(ActivityLog.user_id == user_id).delete(synchronize_session=False)
    db.query(Announcement).filter(Announcement.author_user_id == user_id).delete(synchronize_session=False)
    db.query(Assessment).filter(Assessment.user_id == user_id).delete(synchronize_session=False)
    db.query(Attendance).filter(Attendance.user_id == user_id).delete(synchronize_session=False)
    db.query(FaceEmbedding).filter(FaceEmbedding.user_id == user_id).delete(synchronize_session=False)
    db.query(FaceVerificationLog).filter(FaceVerificationLog.user_id == user_id).delete(synchronize_session=False)
    db.query(Journal).filter(Journal.user_id == user_id).delete(synchronize_session=False)
    db.query(LeaveRequest).filter(LeaveRequest.user_id == user_id).delete(synchronize_session=False)
    db.query(Notification).filter(Notification.user_id == user_id).delete(synchronize_session=False)
    db.query(Participant).filter(Participant.user_id == user_id).delete(synchronize_session=False)
    db.query(Supervisor).filter(Supervisor.user_id == user_id).delete(synchronize_session=False)
    db.delete(target)
    db.commit()

    log_admin_action(
        db,
        current_user.id,
        "permanently_delete_user",
        None,
        f"Hapus permanen akun {target_name} ({target_role})",
        request.client.host if request.client else None,
    )
    db.commit()
    return RedirectResponse(f"{redirect_to}?success=Akun {target_name} berhasil dihapus permanen.", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/backup")
def admin_backup(request: Request, db: Session = Depends(get_db)) -> StreamingResponse:
    """Download SQLite database backup for admin."""
    current_user = get_current_user(request, db)
    if not current_user or current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    from app.config import settings
    import pathlib, shutil, tempfile

    db_url = settings.database_url
    if not db_url.startswith("sqlite"):
        return RedirectResponse("/dashboard?error=Backup hanya tersedia untuk SQLite.", status_code=status.HTTP_303_SEE_OTHER)

    db_path = db_url.replace("sqlite:///", "").replace("sqlite://", "")
    if not pathlib.Path(db_path).exists():
        return RedirectResponse("/dashboard?error=File database tidak ditemukan.", status_code=status.HTTP_303_SEE_OTHER)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    shutil.copy2(db_path, tmp.name)
    tmp.close()

    log_admin_action(db, current_user.id, "backup_database", None, "Download backup database",
                     request.client.host if request.client else None)
    db.commit()

    filename = f"backup-pkl-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"

    def _stream():
        with open(tmp.name, "rb") as f:
            yield from iter(lambda: f.read(65536), b"")
        pathlib.Path(tmp.name).unlink(missing_ok=True)

    return StreamingResponse(
        _stream(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/institutions")
def institutions_page(request: Request, db: Session = Depends(get_db)) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    from app.services.settings_service import (
        get_office_grace_m,
        get_office_latitude,
        get_office_longitude,
        get_office_max_accuracy_m,
        get_office_radius_m,
    )

    office_lat = get_office_latitude(db)
    office_lng = get_office_longitude(db)
    default_geofence = {
        "office_latitude": "" if office_lat is None else str(office_lat),
        "office_longitude": "" if office_lng is None else str(office_lng),
        "office_radius_m": get_office_radius_m(db),
        "office_grace_m": get_office_grace_m(db),
        "office_max_accuracy_m": get_office_max_accuracy_m(db),
    }

    institutions = db.query(Institution).order_by(Institution.id.asc()).all()
    return render_with_user(
        request,
        "institutions.html",
        {"institutions": institutions, "default_geofence": default_geofence},
        current_user,
    )


@router.post("/institutions")
def create_institution(
    request: Request,
    nama_instansi: str = Form(...),
    alamat: str = Form(...),
    kontak: str = Form(...),
    office_latitude: str = Form(""),
    office_longitude: str = Form(""),
    office_radius_m: int | None = Form(None),
    office_grace_m: int | None = Form(None),
    office_max_accuracy_m: int | None = Form(None),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    lat = parse_float_input(office_latitude)
    lng = parse_float_input(office_longitude)

    if (lat is None) != (lng is None):
        return RedirectResponse(
            "/institutions?error=Latitude dan longitude instansi harus diisi berpasangan.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if lat is not None and (lat < -90 or lat > 90):
        return RedirectResponse(
            "/institutions?error=Latitude instansi di luar rentang valid.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if lng is not None and (lng < -180 or lng > 180):
        return RedirectResponse(
            "/institutions?error=Longitude instansi di luar rentang valid.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    radius = office_radius_m
    grace = office_grace_m
    max_accuracy = office_max_accuracy_m
    if lat is not None and radius is None:
        return RedirectResponse(
            "/institutions?error=Radius wajib diisi jika latitude/longitude instansi diisi.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if radius is not None and (radius < 20 or radius > 5000):
        return RedirectResponse(
            "/institutions?error=Radius instansi harus antara 20-5000 meter.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if grace is not None and (grace < 0 or grace > 500):
        return RedirectResponse(
            "/institutions?error=Grace instansi harus antara 0-500 meter.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if max_accuracy is not None and (max_accuracy < 10 or max_accuracy > 500):
        return RedirectResponse(
            "/institutions?error=Akurasi GPS instansi harus antara 10-500 meter.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    institution = Institution(
        nama_instansi=nama_instansi.strip(),
        alamat=alamat.strip() or None,
        kontak=kontak.strip() or None,
        office_latitude=lat,
        office_longitude=lng,
        office_radius_m=radius,
        office_grace_m=grace,
        office_max_accuracy_m=max_accuracy,
    )
    db.add(institution)
    db.commit()
    return RedirectResponse("/institutions", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/institutions/{institution_id}/geofence")
def update_institution_geofence(
    institution_id: int,
    request: Request,
    office_latitude: str = Form(""),
    office_longitude: str = Form(""),
    office_radius_m: int | None = Form(None),
    office_grace_m: int | None = Form(None),
    office_max_accuracy_m: int | None = Form(None),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    institution = db.query(Institution).filter(Institution.id == institution_id).first()
    if not institution:
        return RedirectResponse("/institutions?error=Instansi tidak ditemukan.", status_code=status.HTTP_303_SEE_OTHER)

    lat = parse_float_input(office_latitude)
    lng = parse_float_input(office_longitude)
    if (lat is None) != (lng is None):
        return RedirectResponse(
            "/institutions?error=Latitude dan longitude instansi harus diisi berpasangan.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if lat is not None and (lat < -90 or lat > 90):
        return RedirectResponse(
            "/institutions?error=Latitude instansi di luar rentang valid.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if lng is not None and (lng < -180 or lng > 180):
        return RedirectResponse(
            "/institutions?error=Longitude instansi di luar rentang valid.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if office_radius_m is not None and (office_radius_m < 20 or office_radius_m > 5000):
        return RedirectResponse(
            "/institutions?error=Radius instansi harus antara 20-5000 meter.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if lat is not None and office_radius_m is None:
        return RedirectResponse(
            "/institutions?error=Radius wajib diisi jika latitude/longitude instansi diisi.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if office_grace_m is not None and (office_grace_m < 0 or office_grace_m > 500):
        return RedirectResponse(
            "/institutions?error=Grace instansi harus antara 0-500 meter.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if office_max_accuracy_m is not None and (office_max_accuracy_m < 10 or office_max_accuracy_m > 500):
        return RedirectResponse(
            "/institutions?error=Akurasi GPS instansi harus antara 10-500 meter.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    institution.office_latitude = lat
    institution.office_longitude = lng
    institution.office_radius_m = office_radius_m
    institution.office_grace_m = office_grace_m
    institution.office_max_accuracy_m = office_max_accuracy_m
    db.commit()
    return RedirectResponse("/institutions?success=Geofence instansi berhasil diperbarui.", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/assessments")
def assessments_page(request: Request, db: Session = Depends(get_db)) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    can_manage_assessment = current_user.role in {"admin", "pembimbing"}
    assessments_page_title = "Penilaian Peserta" if can_manage_assessment else "Nilai Saya"

    if can_manage_assessment:
        assessments = db.query(Assessment).order_by(Assessment.id.desc()).limit(200).all()
        participants = db.query(Participant).all()
    else:
        assessments = (
            db.query(Assessment)
            .filter(Assessment.user_id == current_user.id)
            .order_by(Assessment.id.desc())
            .limit(200)
            .all()
        )
        participants = []

    return render_with_user(
        request,
        "assessments.html",
        {
            "assessments": assessments,
            "participants": participants,
            "can_manage_assessment": can_manage_assessment,
            "assessments_page_title": assessments_page_title,
        },
        current_user,
    )


@router.post("/assessments")
def create_assessment(
    request: Request,
    user_id: int = Form(...),
    nilai: int = Form(...),
    catatan: str = Form(""),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role not in {"admin", "pembimbing"}:
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    target_user = db.query(User).filter(User.id == user_id, User.role == "peserta", User.is_active == True).first()
    if not target_user:
        return RedirectResponse("/assessments", status_code=status.HTTP_303_SEE_OTHER)

    assessment = Assessment(user_id=user_id, nilai=nilai, catatan=catatan)
    db.add(assessment)
    db.commit()
    return RedirectResponse("/assessments", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/face-logs")
def face_logs_page(
    request: Request,
    result: str = Query(default="all"),
    action: str = Query(default="all"),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    limit: int = Query(default=100, ge=10, le=500),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    today = datetime.now().date()
    default_from = (today - timedelta(days=6)).isoformat()
    default_to = today.isoformat()

    normalized_from_date = from_date or default_from
    normalized_to_date = to_date or default_to

    from_dt = parse_date_input(normalized_from_date)
    to_dt_start = parse_date_input(normalized_to_date)
    to_dt = datetime.combine(to_dt_start.date(), time(23, 59, 59)) if to_dt_start else None

    query = build_face_log_query(db, result, action, from_dt, to_dt)

    logs = query.order_by(FaceVerificationLog.id.desc()).limit(limit).all()

    user_ids = sorted({row.user_id for row in logs})
    users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
    user_map = {user.id: user.username for user in users}

    cutoff = datetime.now() - timedelta(hours=24)
    metrics_query = db.query(FaceVerificationLog).filter(FaceVerificationLog.created_at >= cutoff)
    total_24h = metrics_query.count()
    success_24h = metrics_query.filter(FaceVerificationLog.matched == True).count()
    failed_24h = metrics_query.filter(FaceVerificationLog.matched == False).count()
    blocked_24h = metrics_query.filter(FaceVerificationLog.attempt_blocked == True).count()
    success_rate_24h = round((success_24h / total_24h) * 100, 2) if total_24h > 0 else 0.0

    # Trend 7 hari terakhir untuk chart ringkas audit.
    trend_labels: list[str] = []
    trend_success: list[int] = []
    trend_failed: list[int] = []
    for delta in range(6, -1, -1):
        day = today - timedelta(days=delta)
        start_day = datetime.combine(day, time(0, 0, 0))
        end_day = datetime.combine(day, time(23, 59, 59))
        day_query = db.query(FaceVerificationLog).filter(
            FaceVerificationLog.created_at >= start_day,
            FaceVerificationLog.created_at <= end_day,
        )
        trend_labels.append(day.strftime("%d/%m"))
        trend_success.append(day_query.filter(FaceVerificationLog.matched == True).count())
        trend_failed.append(day_query.filter(FaceVerificationLog.matched == False).count())

    return render_with_user(
        request,
        "face_logs.html",
        {
            "logs": logs,
            "user_map": user_map,
            "result_filter": result,
            "action_filter": action,
            "from_date_filter": normalized_from_date,
            "to_date_filter": normalized_to_date,
            "limit_filter": limit,
            "total_24h": total_24h,
            "success_24h": success_24h,
            "failed_24h": failed_24h,
            "blocked_24h": blocked_24h,
            "success_rate_24h": success_rate_24h,
            "trend_labels": trend_labels,
            "trend_success": trend_success,
            "trend_failed": trend_failed,
        },
        current_user,
    )


@router.get("/face-logs/export.csv")
def export_face_logs_csv(
    request: Request,
    result: str = Query(default="all"),
    action: str = Query(default="all"),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=10, le=5000),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    today = datetime.now().date()
    normalized_from_date = from_date or (today - timedelta(days=6)).isoformat()
    normalized_to_date = to_date or today.isoformat()

    from_dt = parse_date_input(normalized_from_date)
    to_dt_start = parse_date_input(normalized_to_date)
    to_dt = datetime.combine(to_dt_start.date(), time(23, 59, 59)) if to_dt_start else None

    logs = (
        build_face_log_query(db, result, action, from_dt, to_dt)
        .order_by(FaceVerificationLog.id.desc())
        .limit(limit)
        .all()
    )
    user_ids = sorted({row.user_id for row in logs})
    users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
    user_map = {user.id: user.username for user in users}

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "timestamp",
            "user_id",
            "username",
            "action",
            "matched",
            "attempt_blocked",
            "similarity",
            "confidence",
            "engine",
            "source_ip",
            "message",
        ]
    )

    for row in logs:
        writer.writerow(
            [
                row.id,
                row.created_at.isoformat() if row.created_at else "",
                row.user_id,
                user_map.get(row.user_id, ""),
                row.action,
                row.matched,
                row.attempt_blocked,
                row.similarity if row.similarity is not None else "",
                row.confidence if row.confidence is not None else "",
                row.engine or "",
                row.source_ip or "",
                row.message or "",
            ]
        )

    output.seek(0)
    filename = f"face-verification-logs-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
