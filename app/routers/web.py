from collections import Counter
from datetime import datetime, time, timedelta
import base64
import calendar
import json
from math import atan2, cos, radians, sin, sqrt
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.face_service import FaceRecognitionService
from app.authentication.jwt_handler import hash_password, verify_password
from app.config import settings
from app.database import SessionLocal
from app.models.announcement import Announcement
from app.models.attendance import Attendance
from app.models.assessment import Assessment
from app.models.face_embedding import FaceEmbedding
from app.models.face_verification_log import FaceVerificationLog
from app.models.institution import Institution
from app.models.journal import Journal
from app.models.notification import Notification
from app.models.participant import Participant
from app.models.supervisor import Supervisor
from app.models.user import User
from app.services.journal_signature import (
    generate_journal_signature_token,
    verify_journal_signature_token,
)
from app.services.notifications import push_notification, push_to_role
from app.services.rate_limiter import login_rate_limiter
from app.services.activity import log_activity
from app.services.password_policy import validate_password
from app.services.settings_service import (
    get_attendance_success_auto_hide_seconds,
    get_attendance_transition_style,
    get_jam_masuk,
    get_jam_pulang,
    get_office_grace_m,
    get_office_geofence,
    get_office_max_accuracy_m,
    get_office_radius_m,
    set_setting,
)
from app.security.face_crypto import decrypt_text, encrypt_text

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="app/templates")
face_service = FaceRecognitionService()

_PER_PAGE = 25


def _paginate(query, page: int, per_page: int = _PER_PAGE) -> tuple:
    """Returns (items, total_pages, current_page)."""
    total = query.count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return items, total_pages, page


class FacePayload(BaseModel):
    image_base64: str = Field(min_length=32)
    action: str = Field(default="checkin")
    alasan: str = Field(default="")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session) -> User | None:
    raw_user_id = request.cookies.get("user_id")
    if not raw_user_id:
        return None
    if not raw_user_id.isdigit():
        return None
    user = db.query(User).filter(User.id == int(raw_user_id), User.is_active == True).first()
    if not user:
        return None
    # Validate session_version cookie to support force-logout
    stored_ver = request.cookies.get("session_ver")
    if stored_ver is not None and stored_ver.isdigit():
        if int(stored_ver) != (user.session_version or 1):
            return None
    return user


def render_with_user(request: Request, template_name: str, context: dict[str, object], user: User) -> object:
    payload = {"request": request, "current_user": user, "csrf_token": request.cookies.get("csrf_token", "")}
    payload.update(context)
    return templates.TemplateResponse(request, template_name, payload)


def decode_base64_image(payload: str) -> bytes:
    encoded = payload
    if "," in payload:
        encoded = payload.split(",", 1)[1]
    try:
        return base64.b64decode(encoded)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Format gambar tidak valid") from exc


def calculate_status(now: datetime, db=None) -> str:
    jam_masuk = get_jam_masuk(db) if db else time(8, 15)
    return "terlambat" if now.time() > jam_masuk else "hadir"


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6371000.0
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    r_lat1 = radians(lat1)
    r_lat2 = radians(lat2)

    a = sin(d_lat / 2) ** 2 + cos(r_lat1) * cos(r_lat2) * sin(d_lon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return earth_radius_m * c


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def resolve_effective_office_policy(db: Session, user: User) -> dict[str, object] | None:
    office_geo = get_office_geofence(db)
    global_grace_m = get_office_grace_m(db)
    global_max_accuracy_m = get_office_max_accuracy_m(db)

    policy: dict[str, object] | None = None
    if office_geo:
        office_lat, office_lng, office_radius_m = office_geo
        policy = {
            "latitude": office_lat,
            "longitude": office_lng,
            "radius_m": office_radius_m,
            "grace_m": global_grace_m,
            "max_accuracy_m": global_max_accuracy_m,
            "source": "global",
            "institution_name": None,
        }

    if user.role != "peserta":
        return policy

    participant = db.query(Participant).filter(Participant.user_id == user.id).first()
    if not participant or not participant.instansi:
        return policy

    instansi_name = participant.instansi.strip()
    if not instansi_name:
        return policy

    institution = (
        db.query(Institution)
        .filter(func.lower(func.trim(Institution.nama_instansi)) == instansi_name.lower())
        .first()
    )
    if not institution:
        return policy

    if institution.office_latitude is None or institution.office_longitude is None:
        return policy

    lat = institution.office_latitude
    lng = institution.office_longitude
    if lat < -90 or lat > 90 or lng < -180 or lng > 180:
        return policy

    # Radius/grace/max-accuracy are optional per-institution overrides; fall back to global
    # defaults individually instead of discarding the whole institution geofence when unset.
    global_radius_m = office_geo[2] if office_geo else get_office_radius_m(db)
    radius = _clamp_int(
        int(institution.office_radius_m) if institution.office_radius_m is not None else global_radius_m,
        20, 5000,
    )
    grace = _clamp_int(int(institution.office_grace_m or global_grace_m), 0, 500)
    max_accuracy = _clamp_int(int(institution.office_max_accuracy_m or global_max_accuracy_m), 10, 500)

    return {
        "latitude": lat,
        "longitude": lng,
        "radius_m": radius,
        "grace_m": grace,
        "max_accuracy_m": max_accuracy,
        "source": "institution",
        "institution_name": institution.nama_instansi,
    }


def detect_location_risk(
    db: Session,
    *,
    user_id: int,
    now: datetime,
    latitude: float,
    longitude: float,
) -> tuple[bool, str | None]:
    previous = (
        db.query(Attendance)
        .filter(Attendance.user_id == user_id)
        .filter(Attendance.latitude.isnot(None), Attendance.longitude.isnot(None))
        .order_by(Attendance.id.desc())
        .first()
    )
    if not previous:
        return False, None

    prev_ts = previous.check_out_time or previous.check_in_time or previous.attendance_date
    if not prev_ts:
        return False, None

    elapsed_seconds = (now - prev_ts).total_seconds()
    if elapsed_seconds <= 0:
        return False, None

    traveled_m = haversine_distance_m(previous.latitude, previous.longitude, latitude, longitude)
    speed_mps = traveled_m / elapsed_seconds
    if traveled_m >= 3000 and speed_mps >= 70:
        return True, (
            f"Perpindahan lokasi tidak wajar: {int(traveled_m)}m dalam {int(elapsed_seconds)} detik "
            f"(~{int(speed_mps * 3.6)} km/jam)"
        )

    return False, None


def parse_hhmm(raw: str) -> time | None:
    try:
        return datetime.strptime(raw.strip(), "%H:%M").time()
    except ValueError:
        return None


def get_client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def serialize_embedding_for_storage(embedding: list[float]) -> str:
    payload = json.dumps(embedding, separators=(",", ":"))
    encrypted = encrypt_text(payload)
    return f"enc::{encrypted}"


def deserialize_embedding_from_storage(raw_value: str) -> tuple[list[float], bool]:
    # bool indicates whether legacy plain JSON format was detected.
    if raw_value.startswith("enc::"):
        decrypted = decrypt_text(raw_value[5:])
        return json.loads(decrypted), False
    return json.loads(raw_value), True


def log_face_verification(
    db: Session,
    *,
    user_id: int,
    action: str,
    matched: bool,
    source_ip: str | None,
    attempt_blocked: bool = False,
    similarity: float | None = None,
    confidence: float | None = None,
    engine: str | None = None,
    message: str | None = None,
) -> None:
    db.add(
        FaceVerificationLog(
            user_id=user_id,
            action=action,
            matched=matched,
            attempt_blocked=attempt_blocked,
            similarity=similarity,
            confidence=confidence,
            engine=engine,
            message=message,
            source_ip=source_ip,
        )
    )


def check_face_lock(db: Session, user_id: int) -> bool:
    cutoff = datetime.now() - timedelta(minutes=settings.face_lock_minutes)
    failed_attempts = (
        db.query(FaceVerificationLog)
        .filter(FaceVerificationLog.user_id == user_id)
        .filter(FaceVerificationLog.matched == False)
        .filter(FaceVerificationLog.created_at >= cutoff)
        .count()
    )
    return failed_attempts >= settings.face_max_failed_attempts


def build_signature_verify_url(request: Request, token: str) -> str:
    return str(request.url_for("journal_signature_page", token=token))


def build_signature_qr_url(verify_url: str) -> str:
    encoded = quote(verify_url, safe="")
    return f"https://api.qrserver.com/v1/create-qr-code/?size=220x220&data={encoded}"


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
    ip_key = request.client.host if request.client else "unknown"
    identifier = email.strip()
    email_key = identifier.lower()

    if login_rate_limiter.is_blocked(ip_key) or login_rate_limiter.is_blocked(email_key):
        wait = max(login_rate_limiter.remaining_seconds(ip_key), login_rate_limiter.remaining_seconds(email_key))
        mins = max(1, wait // 60)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"request": request, "error": f"Terlalu banyak percobaan gagal. Coba lagi dalam {mins} menit."},
        )

    # Login boleh pakai username atau email
    user = db.query(User).filter((User.email == identifier) | (User.username == identifier)).first()
    if user and verify_password(password, user.password_hash):
        login_rate_limiter.reset(ip_key)
        login_rate_limiter.reset(email_key)
        from app.database import SessionLocal as _SL
        _db2 = _SL()
        try:
            log_activity(_db2, user.id, "login", f"Login dari {ip_key}")
            _db2.commit()
        finally:
            _db2.close()
        response = RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            "user_id",
            str(user.id),
            httponly=True,
            samesite=settings.cookie_samesite,
            secure=settings.cookie_secure,
        )
        response.set_cookie(
            "session_ver",
            str(user.session_version or 1),
            httponly=True,
            samesite=settings.cookie_samesite,
            secure=settings.cookie_secure,
        )
        return response

    login_rate_limiter.record_attempt(ip_key)
    login_rate_limiter.record_attempt(email_key)
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

    pw_err = validate_password(password)
    if pw_err:
        return templates.TemplateResponse(
            request, "register.html", {"request": request, "error": pw_err}
        )

    user = User(username=username, email=email, password_hash=hash_password(password), role="peserta")
    db.add(user)
    db.commit()
    db.refresh(user)
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    current_user = get_current_user(request, db)
    if current_user:
        current_user.session_version = (current_user.session_version or 1) + 1
        db.commit()
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("user_id")
    response.delete_cookie("session_ver")
    return response


@router.get("/profile")
def profile_page(request: Request, db: Session = Depends(get_db)) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    participant = db.query(Participant).filter(Participant.user_id == current_user.id).first() if current_user.role == "peserta" else None
    institution_names = [row.nama_instansi for row in db.query(Institution).order_by(Institution.nama_instansi.asc()).all()]
    return render_with_user(request, "profile.html", {"participant": participant, "institution_names": institution_names}, current_user)


@router.post("/profile")
def update_profile(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    conflict = db.query(User).filter(
        ((User.email == email) | (User.username == username)) & (User.id != current_user.id)
    ).first()
    if conflict:
        return RedirectResponse("/profile?error=Username atau email sudah dipakai akun lain.", status_code=status.HTTP_303_SEE_OTHER)

    current_user.username = username.strip()
    current_user.email = email.strip()
    db.commit()
    return RedirectResponse("/profile?success=Profil berhasil diperbarui.", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/profile/participant")
def update_participant_profile(
    request: Request,
    nama_lengkap: str = Form(...),
    jurusan: str = Form(""),
    instansi: str = Form(""),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user or current_user.role != "peserta":
        return RedirectResponse("/profile", status_code=status.HTTP_303_SEE_OTHER)

    participant = db.query(Participant).filter(Participant.user_id == current_user.id).first()
    if participant:
        participant.nama_lengkap = nama_lengkap.strip()
        participant.jurusan = jurusan.strip() or None
        participant.instansi = instansi.strip() or None
    else:
        participant = Participant(
            user_id=current_user.id,
            nama_lengkap=nama_lengkap.strip(),
            jurusan=jurusan.strip() or None,
            instansi=instansi.strip() or None,
        )
        db.add(participant)

    log_activity(db, current_user.id, "update_participant_profile", f"Profil PKL diperbarui: {nama_lengkap.strip()}")
    db.commit()
    return RedirectResponse("/profile?success=Data PKL berhasil disimpan.", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/profile/password")
def change_own_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    if not verify_password(current_password, current_user.password_hash):
        return RedirectResponse("/profile?error=Password lama tidak sesuai.", status_code=status.HTTP_303_SEE_OTHER)

    pw_err = validate_password(new_password.strip())
    if pw_err:
        return RedirectResponse(f"/profile?error={pw_err}", status_code=status.HTTP_303_SEE_OTHER)

    current_user.password_hash = hash_password(new_password.strip())
    db.commit()
    return RedirectResponse("/profile?success=Password berhasil diubah.", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/api/notifications")
def get_notifications(request: Request, db: Session = Depends(get_db)) -> dict:
    current_user = get_current_user(request, db)
    if not current_user:
        return {"unread": 0, "items": []}

    items = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.id.desc())
        .limit(20)
        .all()
    )
    unread = sum(1 for n in items if not n.is_read)
    return {
        "unread": unread,
        "items": [
            {
                "id": n.id,
                "message": n.message,
                "type": n.type,
                "is_read": n.is_read,
                "created_at": n.created_at.strftime("%d/%m/%Y %H:%M") if n.created_at else "",
            }
            for n in items
        ],
    }


@router.post("/api/notifications/{notif_id}/read")
def mark_notification_read(notif_id: int, request: Request, db: Session = Depends(get_db)) -> dict:
    current_user = get_current_user(request, db)
    if not current_user:
        return {"ok": False}

    n = db.query(Notification).filter(Notification.id == notif_id, Notification.user_id == current_user.id).first()
    if n:
        n.is_read = True
        db.commit()
    return {"ok": True}


@router.post("/api/notifications/read-all")
def mark_all_read(request: Request, db: Session = Depends(get_db)) -> dict:
    current_user = get_current_user(request, db)
    if not current_user:
        return {"ok": False}

    db.query(Notification).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).update({"is_read": True})
    db.commit()
    return {"ok": True}


@router.get("/dashboard")
def dashboard_page(request: Request, db: Session = Depends(get_db)) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    role_titles = {
        "admin": "Dashboard Admin",
        "pembimbing": "Dashboard Pembimbing",
        "peserta": "Dashboard Peserta",
    }

    role_descriptions = {
        "admin": "Pantau statistik sistem, tata kelola data master, dan kualitas laporan PKL.",
        "pembimbing": "Fokus pada progres peserta, verifikasi jurnal, dan evaluasi hasil pembinaan.",
        "peserta": "Lihat progres pribadi, kedisiplinan absensi, dan tindak lanjut jurnal harian.",
    }

    role_quick_links: dict[str, list[dict[str, str]]] = {
        "admin": [
            {"label": "Kelola Peserta", "href": "/participants", "hint": "Tambah dan perbarui data peserta"},
            {"label": "Kelola Pembimbing", "href": "/supervisors", "hint": "Atur akun pembimbing PKL"},
            {"label": "Audit Verifikasi Wajah", "href": "/face-logs", "hint": "Pantau log verifikasi dan lock"},
            {"label": "Laporan PDF", "href": "/api/reports/attendance/pdf", "hint": "Ekspor rekap absensi"},
        ],
        "pembimbing": [
            {"label": "Verifikasi Jurnal", "href": "/journal", "hint": "Pantau jurnal harian peserta"},
            {"label": "Input Penilaian", "href": "/assessments", "hint": "Berikan nilai dan catatan"},
            {"label": "Data Absensi", "href": "/attendance", "hint": "Cek disiplin kehadiran peserta"},
        ],
        "peserta": [
            {"label": "Absensi Wajah", "href": "/attendance", "hint": "Lakukan check-in / check-out"},
            {"label": "Jurnal Harian", "href": "/journal", "hint": "Catat kegiatan PKL hari ini"},
        ],
    }

    metrics: list[dict[str, object]] = []
    recent_attendance: list[Attendance] = []
    recent_journal: list[Journal] = []
    chart_source: list[Attendance] = []
    chart_title = "Distribusi Status Absensi"

    review_filter = (request.query_params.get("review_filter") or "all").strip().lower()

    if current_user.role == "admin":
        metrics = [
            {
                "label": "Total Pengguna",
                "value": db.query(User).count(),
                "hint": "Admin, pembimbing, dan peserta aktif",
            },
            {
                "label": "Total Peserta",
                "value": db.query(Participant).count(),
                "hint": "Peserta PKL terdaftar",
            },
            {
                "label": "Total Pembimbing",
                "value": db.query(Supervisor).count(),
                "hint": "Pembimbing internal aktif",
            },
            {
                "label": "Instansi Mitra",
                "value": db.query(Institution).count(),
                "hint": "Mitra instansi untuk penempatan PKL",
            },
            {
                "label": "Absensi Tercatat",
                "value": db.query(Attendance).count(),
                "hint": "Akumulasi transaksi absensi",
            },
            {
                "label": "Jurnal Pending",
                "value": db.query(Journal).filter(Journal.status == "pending").count(),
                "hint": "Perlu review pembimbing",
            },
        ]
        recent_attendance_query = db.query(Attendance)
        if review_filter == "pending":
            recent_attendance_query = recent_attendance_query.filter(Attendance.location_review_status == "pending")
        elif review_filter == "approved":
            recent_attendance_query = recent_attendance_query.filter(Attendance.location_review_status == "approved")
        elif review_filter == "rejected":
            recent_attendance_query = recent_attendance_query.filter(Attendance.location_review_status == "rejected")
        elif review_filter == "grace":
            recent_attendance_query = recent_attendance_query.filter(
                Attendance.location_review_reason.in_(["grace", "grace_and_risk"])
            )
        elif review_filter == "risk":
            recent_attendance_query = recent_attendance_query.filter(
                Attendance.location_review_reason.in_(["risk", "grace_and_risk"])
            )
        recent_attendance = recent_attendance_query.order_by(Attendance.id.desc()).limit(7).all()
        recent_journal = db.query(Journal).order_by(Journal.id.desc()).limit(7).all()
        chart_source = db.query(Attendance).order_by(Attendance.id.desc()).limit(80).all()
        chart_title = "Distribusi Status Absensi Sistem"
    elif current_user.role == "pembimbing":
        avg_score = db.query(func.avg(Assessment.nilai)).scalar() or 0
        today_attendance_count = (
            db.query(Attendance)
            .filter(func.date(Attendance.attendance_date) == datetime.now().date())
            .count()
        )
        metrics = [
            {
                "label": "Peserta Dipantau",
                "value": db.query(Participant).count(),
                "hint": "Total peserta dalam sistem",
            },
            {
                "label": "Absensi Hari Ini",
                "value": today_attendance_count,
                "hint": "Jumlah absensi masuk hari ini",
            },
            {
                "label": "Jurnal Pending",
                "value": db.query(Journal).filter(Journal.status == "pending").count(),
                "hint": "Menunggu verifikasi",
            },
            {
                "label": "Rata-rata Nilai",
                "value": round(float(avg_score), 1),
                "hint": "Rata-rata evaluasi peserta",
            },
        ]
        recent_attendance = db.query(Attendance).order_by(Attendance.id.desc()).limit(7).all()
        recent_journal = db.query(Journal).order_by(Journal.id.desc()).limit(7).all()
        chart_source = db.query(Attendance).order_by(Attendance.id.desc()).limit(60).all()
        chart_title = "Komposisi Status Absensi Peserta"
    else:
        avg_personal_score = (
            db.query(func.avg(Assessment.nilai)).filter(Assessment.user_id == current_user.id).scalar() or 0
        )
        metrics = [
            {
                "label": "Total Absensi Saya",
                "value": db.query(Attendance).filter(Attendance.user_id == current_user.id).count(),
                "hint": "Riwayat kehadiran pribadi",
            },
            {
                "label": "Kehadiran Tepat Waktu",
                "value": (
                    db.query(Attendance)
                    .filter(Attendance.user_id == current_user.id)
                    .filter(Attendance.status == "hadir")
                    .count()
                ),
                "hint": "Status hadir",
            },
            {
                "label": "Jurnal Saya",
                "value": db.query(Journal).filter(Journal.user_id == current_user.id).count(),
                "hint": "Jurnal yang sudah dikirim",
            },
            {
                "label": "Jurnal Menunggu Review",
                "value": (
                    db.query(Journal)
                    .filter(Journal.user_id == current_user.id)
                    .filter(Journal.status == "pending")
                    .count()
                ),
                "hint": "Butuh tindak lanjut",
            },
            {
                "label": "Nilai Rata-rata",
                "value": round(float(avg_personal_score), 1),
                "hint": "Rangkuman evaluasi pembimbing",
            },
        ]
        recent_attendance = (
            db.query(Attendance)
            .filter(Attendance.user_id == current_user.id)
            .order_by(Attendance.id.desc())
            .limit(7)
            .all()
        )
        recent_journal = (
            db.query(Journal)
            .filter(Journal.user_id == current_user.id)
            .order_by(Journal.id.desc())
            .limit(7)
            .all()
        )
        chart_source = (
            db.query(Attendance)
            .filter(Attendance.user_id == current_user.id)
            .order_by(Attendance.id.desc())
            .limit(40)
            .all()
        )
        chart_title = "Distribusi Status Absensi Saya"

    status_counter = Counter([item.status for item in chart_source if item.status])
    chart_labels = ["hadir", "terlambat", "izin", "sakit", "alpa"]
    chart_values = [status_counter.get(label, 0) for label in chart_labels]

    announcements = (
        db.query(Announcement)
        .filter(Announcement.is_active == True)
        .order_by(Announcement.id.desc())
        .limit(5)
        .all()
    )

    # PKL progress for peserta role
    pkl_progress: dict | None = None
    if current_user.role == "peserta":
        participant = db.query(Participant).filter(Participant.user_id == current_user.id).first()
        if participant and participant.tanggal_mulai and participant.tanggal_selesai:
            today = datetime.now().date()
            total_days = (participant.tanggal_selesai.date() - participant.tanggal_mulai.date()).days
            elapsed_days = (today - participant.tanggal_mulai.date()).days
            pct = min(100, max(0, int(elapsed_days / total_days * 100))) if total_days > 0 else 0
            sisa = (participant.tanggal_selesai.date() - today).days
            pkl_progress = {
                "mulai": participant.tanggal_mulai.strftime("%d/%m/%Y"),
                "selesai": participant.tanggal_selesai.strftime("%d/%m/%Y"),
                "pct": pct,
                "sisa": sisa,
                "hampir_selesai": sisa <= 7 and sisa >= 0,
            }

    # Pembimbing extra data: peserta belum absen hari ini + rata kehadiran
    pembimbing_extra: dict | None = None
    if current_user.role == "pembimbing":
        today_date = datetime.now().date()
        all_peserta = db.query(User).filter(User.role == "peserta", User.is_active == True).all()
        absen_today_ids = {
            row.user_id for row in db.query(Attendance.user_id)
            .filter(func.date(Attendance.attendance_date) == today_date)
            .all()
        }
        belum_absen = [u for u in all_peserta if u.id not in absen_today_ids]
        pembimbing_extra = {"belum_absen": belum_absen}

    attendance_settings = None
    review_sla = None
    if current_user.role == "admin":
        attendance_settings = {
            "jam_masuk": get_jam_masuk(db).strftime("%H:%M"),
            "jam_pulang": get_jam_pulang(db).strftime("%H:%M"),
            "success_auto_hide_seconds": get_attendance_success_auto_hide_seconds(db),
            "transition_style": get_attendance_transition_style(db),
        }

        pending_reviews = db.query(Attendance).filter(
            Attendance.requires_location_review == True,
            Attendance.location_review_status == "pending",
        ).all()
        now_ts = datetime.now()
        lt24 = 0
        bt24_72 = 0
        gt72 = 0
        for row in pending_reviews:
            age_hours = (now_ts - (row.attendance_date or now_ts)).total_seconds() / 3600
            if age_hours < 24:
                lt24 += 1
            elif age_hours <= 72:
                bt24_72 += 1
            else:
                gt72 += 1
        review_sla = {
            "total": len(pending_reviews),
            "lt24": lt24,
            "bt24_72": bt24_72,
            "gt72": gt72,
        }

    return render_with_user(
        request,
        "dashboard.html",
        {
            "dashboard_role": current_user.role,
            "dashboard_title": role_titles.get(current_user.role, "Dashboard"),
            "dashboard_description": role_descriptions.get(current_user.role, "Ringkasan aktivitas."),
            "metrics": metrics,
            "recent_attendance": recent_attendance,
            "recent_journal": recent_journal,
            "chart_labels": chart_labels,
            "chart_values": chart_values,
            "chart_title": chart_title,
            "quick_links": role_quick_links.get(current_user.role, []),
            "announcements": announcements,
            "pkl_progress": pkl_progress,
            "pembimbing_extra": pembimbing_extra,
            "attendance_settings": attendance_settings,
            "review_filter": review_filter,
            "review_sla": review_sla,
        },
        current_user,
    )


@router.post("/admin/attendance-settings")
def update_attendance_settings(
    request: Request,
    jam_masuk: str = Form(...),
    jam_pulang: str = Form(...),
    success_auto_hide_seconds: int | None = Form(None),
    transition_style: str = Form("normal"),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    jam_masuk_time = parse_hhmm(jam_masuk)
    jam_pulang_time = parse_hhmm(jam_pulang)
    if not jam_masuk_time or not jam_pulang_time:
        return RedirectResponse(
            "/dashboard?error=Format jam tidak valid. Gunakan HH:MM.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if jam_pulang_time <= jam_masuk_time:
        return RedirectResponse(
            "/dashboard?error=Jam pulang harus lebih besar dari jam masuk.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    style = transition_style.strip().lower()
    if style not in {"fast", "normal", "slow"}:
        return RedirectResponse(
            "/dashboard?error=Mode transisi tidak valid.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    auto_hide_seconds = success_auto_hide_seconds
    if auto_hide_seconds is None:
        auto_hide_seconds = get_attendance_success_auto_hide_seconds(db)
    if auto_hide_seconds < 3 or auto_hide_seconds > 20:
        return RedirectResponse(
            "/dashboard?error=Durasi auto-hide harus antara 3-20 detik.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    set_setting(db, "jam_masuk", jam_masuk_time.strftime("%H:%M"))
    set_setting(db, "jam_pulang", jam_pulang_time.strftime("%H:%M"))
    set_setting(db, "attendance_success_auto_hide_seconds", str(auto_hide_seconds))
    set_setting(db, "attendance_transition_style", style)
    log_activity(
        db,
        current_user.id,
        "update_attendance_settings",
        (
            f"Set jam masuk={jam_masuk_time.strftime('%H:%M')} "
            f"jam pulang={jam_pulang_time.strftime('%H:%M')} "
            f"auto-hide={auto_hide_seconds}s transisi={style}"
        ),
    )
    db.commit()
    return RedirectResponse(
        "/dashboard?success=Pengaturan jam absensi berhasil diperbarui.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/office-geofence")
def update_office_geofence(
    request: Request,
    office_latitude: str = Form(""),
    office_longitude: str = Form(""),
    office_radius_m: int = Form(200),
    office_grace_m: int = Form(15),
    office_max_accuracy_m: int = Form(80),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role != "admin":
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    lat_raw = office_latitude.strip()
    lng_raw = office_longitude.strip()
    if not lat_raw or not lng_raw:
        return RedirectResponse(
            "/institutions?error=Latitude dan longitude kantor wajib diisi.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    try:
        office_lat = float(lat_raw)
        office_lng = float(lng_raw)
    except ValueError:
        return RedirectResponse(
            "/institutions?error=Format latitude/longitude kantor tidak valid.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if office_lat < -90 or office_lat > 90 or office_lng < -180 or office_lng > 180:
        return RedirectResponse(
            "/institutions?error=Latitude/longitude kantor di luar rentang valid.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if office_radius_m < 20 or office_radius_m > 5000:
        return RedirectResponse(
            "/institutions?error=Radius kantor harus antara 20-5000 meter.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if office_grace_m < 0 or office_grace_m > 500:
        return RedirectResponse(
            "/institutions?error=Grace radius harus antara 0-500 meter.",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if office_max_accuracy_m < 10 or office_max_accuracy_m > 500:
        return RedirectResponse(
            "/institutions?error=Batas akurasi GPS harus antara 10-500 meter.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    set_setting(db, "office_latitude", f"{office_lat:.7f}")
    set_setting(db, "office_longitude", f"{office_lng:.7f}")
    set_setting(db, "office_radius_m", str(office_radius_m))
    set_setting(db, "office_grace_m", str(office_grace_m))
    set_setting(db, "office_max_accuracy_m", str(office_max_accuracy_m))
    log_activity(
        db,
        current_user.id,
        "update_office_geofence",
        (
            f"office=({office_lat:.5f},{office_lng:.5f}) radius={office_radius_m}m "
            f"grace={office_grace_m}m max-accuracy={office_max_accuracy_m}m"
        ),
    )
    db.commit()
    return RedirectResponse(
        "/institutions?success=Geofence default kantor berhasil diperbarui.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/participants")
def participants_page(request: Request, page: int = 1, db: Session = Depends(get_db)) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role not in {"admin", "pembimbing"}:
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    q = db.query(Participant).order_by(Participant.id.desc())
    participants, total_pages, current_page = _paginate(q, page)

    # All peserta accounts (including those without participant profiles)
    all_peserta_users = db.query(User).filter(User.role == "peserta", User.is_active == True).all()
    participant_user_ids = {p.user_id for p in db.query(Participant).all()}
    users_without_profile = [u for u in all_peserta_users if u.id not in participant_user_ids]

    users = db.query(User).filter(User.role == "peserta").all()
    institution_names = [row.nama_instansi for row in db.query(Institution).order_by(Institution.nama_instansi.asc()).all()]
    return render_with_user(
        request,
        "participants.html",
        {
            "participants": participants,
            "users": users,
            "can_manage_password": current_user.role == "admin",
            "total_pages": total_pages,
            "current_page": current_page,
            "base_url": "/participants",
            "users_without_profile": users_without_profile,
            "institution_names": institution_names,
        },
        current_user,
    )


@router.post("/participants")
def create_participant(
    request: Request,
    nama_lengkap: str = Form(...),
    jurusan: str = Form(...),
    instansi: str = Form(...),
    user_id: int = Form(...),
    tanggal_mulai: str = Form(...),
    tanggal_selesai: str = Form(...),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role not in {"admin", "pembimbing"}:
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    existing_participant = db.query(Participant).filter(Participant.user_id == user_id).first()
    if existing_participant:
        return RedirectResponse("/participants", status_code=status.HTTP_303_SEE_OTHER)

    try:
        mulai = datetime.strptime(tanggal_mulai.strip(), "%Y-%m-%d")
        selesai = datetime.strptime(tanggal_selesai.strip(), "%Y-%m-%d")
    except ValueError:
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
    db.commit()
    return RedirectResponse("/participants", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/attendance")
def attendance_page(request: Request, page: int = 1, review_filter: str = "all", db: Session = Depends(get_db)) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    can_manage_attendance = current_user.role in {"admin", "pembimbing"}
    show_face_panel = current_user.role == "peserta"
    attendance_page_title = "Absensi Peserta" if can_manage_attendance else "Absensi Saya"
    has_face_registered = (
        db.query(FaceEmbedding).filter(FaceEmbedding.user_id == current_user.id).first() is not None
        if show_face_panel else False
    )
    just_registered = show_face_panel and request.query_params.get("registered") == "1"

    if can_manage_attendance:
        q = db.query(Attendance)
        rf = review_filter.strip().lower()
        if rf == "pending":
            q = q.filter(Attendance.location_review_status == "pending")
        elif rf == "approved":
            q = q.filter(Attendance.location_review_status == "approved")
        elif rf == "rejected":
            q = q.filter(Attendance.location_review_status == "rejected")
        elif rf == "grace":
            q = q.filter(Attendance.location_review_reason.in_(["grace", "grace_and_risk"]))
        elif rf == "risk":
            q = q.filter(Attendance.location_review_reason.in_(["risk", "grace_and_risk"]))
        q = q.order_by(Attendance.id.desc())
        attendance, total_pages, current_page = _paginate(q, page)
        users = db.query(User).filter(User.role == "peserta", User.is_active == True).all()
    else:
        q = db.query(Attendance).filter(Attendance.user_id == current_user.id).order_by(Attendance.id.desc())
        attendance, total_pages, current_page = _paginate(q, page)
        users = [current_user]

    attendance_ui_config = {
        "success_auto_hide_seconds": get_attendance_success_auto_hide_seconds(db),
        "transition_style": get_attendance_transition_style(db),
        "office_radius_m": get_office_radius_m(db),
        "office_grace_m": get_office_grace_m(db),
        "office_max_accuracy_m": get_office_max_accuracy_m(db),
        "office_policy_source": "global",
    }
    if show_face_panel:
        effective_policy = resolve_effective_office_policy(db, current_user)
        if effective_policy:
            attendance_ui_config["office_radius_m"] = effective_policy["radius_m"]
            attendance_ui_config["office_grace_m"] = effective_policy["grace_m"]
            attendance_ui_config["office_max_accuracy_m"] = effective_policy["max_accuracy_m"]
            attendance_ui_config["office_policy_source"] = effective_policy["source"]
            attendance_ui_config["office_institution_name"] = effective_policy.get("institution_name")

    return render_with_user(
        request,
        "attendance.html",
        {
            "attendance": attendance,
            "users": users,
            "can_manage_attendance": can_manage_attendance,
            "show_face_panel": show_face_panel,
            "has_face_registered": has_face_registered,
            "just_registered": just_registered,
            "attendance_page_title": attendance_page_title,
            "attendance_ui_config": attendance_ui_config,
            "review_filter": review_filter,
            "total_pages": total_pages,
            "current_page": current_page,
            "base_url": "/attendance" + ("?review_filter=" + review_filter if can_manage_attendance and review_filter != "all" else ""),
        },
        current_user,
    )


@router.get("/location-reviews")
def location_reviews_page(request: Request, page: int = 1, review_filter: str = "pending", db: Session = Depends(get_db)) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role not in {"admin", "pembimbing"}:
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    rf = review_filter.strip().lower()
    q = db.query(Attendance).filter(Attendance.requires_location_review == True)
    if rf == "pending":
        q = q.filter(Attendance.location_review_status == "pending")
    elif rf == "approved":
        q = q.filter(Attendance.location_review_status == "approved")
    elif rf == "rejected":
        q = q.filter(Attendance.location_review_status == "rejected")
    elif rf == "grace":
        q = q.filter(Attendance.location_review_reason.in_(["grace", "grace_and_risk"]))
    elif rf == "risk":
        q = q.filter(Attendance.location_review_reason.in_(["risk", "grace_and_risk"]))
    q = q.order_by(Attendance.id.desc())

    reviews, total_pages, current_page = _paginate(q, page)

    reviewer_ids = [x.location_reviewed_by_user_id for x in reviews if x.location_reviewed_by_user_id]
    reviewer_map = {
        user.id: user.username
        for user in db.query(User).filter(User.id.in_(reviewer_ids)).all()
    } if reviewer_ids else {}

    now = datetime.now()
    pending_all = db.query(Attendance).filter(
        Attendance.requires_location_review == True,
        Attendance.location_review_status == "pending",
    ).all()
    pending_lt24 = 0
    pending_24_72 = 0
    pending_gt72 = 0
    for row in pending_all:
        age_hours = (now - (row.attendance_date or now)).total_seconds() / 3600
        if age_hours < 24:
            pending_lt24 += 1
        elif age_hours <= 72:
            pending_24_72 += 1
        else:
            pending_gt72 += 1

    age_hours_map = {
        row.id: int((now - (row.attendance_date or now)).total_seconds() / 3600)
        for row in reviews
    }

    return render_with_user(
        request,
        "location_reviews.html",
        {
            "reviews": reviews,
            "review_filter": rf,
            "reviewer_map": reviewer_map,
            "age_hours_map": age_hours_map,
            "pending_lt24": pending_lt24,
            "pending_24_72": pending_24_72,
            "pending_gt72": pending_gt72,
            "total_pending": len(pending_all),
            "total_pages": total_pages,
            "current_page": current_page,
            "base_url": "/location-reviews" + ("?review_filter=" + rf if rf != "pending" else ""),
        },
        current_user,
    )


@router.post("/attendance/{attendance_id}/location-review")
def review_attendance_location(
    attendance_id: int,
    request: Request,
    decision: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role not in {"admin", "pembimbing"}:
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    attendance = db.query(Attendance).filter(Attendance.id == attendance_id).first()
    if not attendance:
        return RedirectResponse("/attendance?error=Data absensi tidak ditemukan.", status_code=status.HTTP_303_SEE_OTHER)

    decision_norm = decision.strip().lower()
    if decision_norm not in {"approved", "rejected", "pending", "reset"}:
        return RedirectResponse("/attendance?error=Keputusan review tidak valid.", status_code=status.HTTP_303_SEE_OTHER)

    if decision_norm == "reset":
        attendance.location_review_status = "pending" if attendance.requires_location_review else "not_required"
        attendance.location_review_note = None
        attendance.location_reviewed_by_user_id = None
        attendance.location_reviewed_at = None
    else:
        attendance.location_review_status = decision_norm
        attendance.location_review_note = note.strip() or None
        attendance.location_reviewed_by_user_id = current_user.id
        attendance.location_reviewed_at = datetime.now()

    log_activity(
        db,
        current_user.id,
        "review_attendance_location",
        f"attendance_id={attendance.id} decision={attendance.location_review_status}",
    )
    db.commit()
    return RedirectResponse("/attendance?success=Review lokasi absensi berhasil diperbarui.", status_code=status.HTTP_303_SEE_OTHER)


MONTH_NAMES_ID = [
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]


@router.get("/attendance/calendar")
def attendance_calendar_page(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    user_id: int | None = None,
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    can_manage_attendance = current_user.role in {"admin", "pembimbing"}

    today = datetime.now()
    year = year or today.year
    month = month or today.month
    if month < 1:
        month, year = 12, year - 1
    elif month > 12:
        month, year = 1, year + 1

    users: list[User] = []
    target_user_id = current_user.id
    if can_manage_attendance:
        users = db.query(User).filter(User.role == "peserta", User.is_active == True).order_by(User.username.asc()).all()
        if user_id and any(u.id == user_id for u in users):
            target_user_id = user_id
        elif users:
            target_user_id = users[0].id
        else:
            target_user_id = None

    target_user = db.query(User).filter(User.id == target_user_id).first() if target_user_id else None

    days_in_month = calendar.monthrange(year, month)[1]
    first_day = datetime(year, month, 1)
    last_day = datetime(year, month, days_in_month, 23, 59, 59)

    rows: list[Attendance] = []
    if target_user_id:
        rows = (
            db.query(Attendance)
            .filter(Attendance.user_id == target_user_id)
            .filter(Attendance.attendance_date >= first_day, Attendance.attendance_date <= last_day)
            .order_by(Attendance.id.asc())
            .all()
        )

    by_day: dict[int, Attendance] = {}
    for row in rows:
        if row.attendance_date:
            by_day[row.attendance_date.day] = row

    month_grid = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    weeks = []
    for week in month_grid:
        week_cells = []
        for day_num in week:
            if day_num == 0:
                week_cells.append(None)
                continue
            att = by_day.get(day_num)
            week_cells.append({
                "day": day_num,
                "status": att.status if att else None,
                "check_in": att.check_in_time.strftime("%H:%M") if att and att.check_in_time else None,
                "check_out": att.check_out_time.strftime("%H:%M") if att and att.check_out_time else None,
                "is_today": year == today.year and month == today.month and day_num == today.day,
            })
        weeks.append(week_cells)

    status_counts = Counter([row.status for row in rows if row.status])

    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)

    return render_with_user(
        request,
        "attendance_calendar.html",
        {
            "weeks": weeks,
            "year": year,
            "month": month,
            "month_name": MONTH_NAMES_ID[month - 1],
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
            "can_manage_attendance": can_manage_attendance,
            "users": users,
            "target_user_id": target_user_id,
            "target_user": target_user,
            "status_counts": status_counts,
        },
        current_user,
    )


@router.post("/attendance")
def create_attendance(
    request: Request,
    user_id: int = Form(...),
    status: str = Form(...),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role not in {"admin", "pembimbing"}:
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    target_user = db.query(User).filter(User.id == user_id, User.role == "peserta", User.is_active == True).first()
    if not target_user:
        return RedirectResponse("/attendance", status_code=status.HTTP_303_SEE_OTHER)

    attendance = Attendance(user_id=user_id, status=status)
    db.add(attendance)
    db.commit()
    return RedirectResponse("/attendance", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/journal")
def journal_page(request: Request, page: int = 1, db: Session = Depends(get_db)) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    can_manage_journal = current_user.role in {"admin", "pembimbing"}
    journal_page_title = "Verifikasi Jurnal Peserta" if can_manage_journal else "Jurnal Harian Saya"

    if can_manage_journal:
        q = db.query(Journal).order_by(Journal.id.desc())
        journals, total_pages, current_page = _paginate(q, page)
        users = db.query(User).filter(User.role == "peserta", User.is_active == True).all()
    else:
        q = db.query(Journal).filter(Journal.user_id == current_user.id).order_by(Journal.id.desc())
        journals, total_pages, current_page = _paginate(q, page)
        users = [current_user]

    signature_links: dict[int, dict[str, str]] = {}
    for row in journals:
        if not row.signature_token:
            continue
        verify_url = build_signature_verify_url(request, row.signature_token)
        signature_links[row.id] = {
            "verify_url": verify_url,
            "qr_url": build_signature_qr_url(verify_url),
        }

    return render_with_user(
        request,
        "journal.html",
        {
            "journals": journals,
            "users": users,
            "can_manage_journal": can_manage_journal,
            "journal_page_title": journal_page_title,
            "signature_links": signature_links,
            "total_pages": total_pages, "current_page": current_page, "base_url": "/journal",
        },
        current_user,
    )


@router.post("/journal")
def create_journal_web(
    request: Request,
    user_id: int | None = Form(None),
    kegiatan: str = Form(...),
    output: str = Form(""),
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    if current_user.role in {"admin", "pembimbing"}:
        if not user_id:
            return RedirectResponse("/journal", status_code=status.HTTP_303_SEE_OTHER)
        target_user = db.query(User).filter(User.id == user_id, User.role == "peserta", User.is_active == True).first()
        if not target_user:
            return RedirectResponse("/journal", status_code=status.HTTP_303_SEE_OTHER)
        selected_user_id = user_id
    else:
        selected_user_id = current_user.id

    # Validasi: max 3 jurnal per hari per peserta
    from sqlalchemy import func as _func, cast, Date as _Date
    today_count = db.query(Journal).filter(
        Journal.user_id == selected_user_id,
        _func.date(Journal.tanggal) == datetime.now().date(),
    ).count()
    if today_count >= 3:
        return RedirectResponse("/journal?error=Maksimal 3 jurnal per hari sudah tercapai.", status_code=status.HTTP_303_SEE_OTHER)

    if len(kegiatan.strip()) < 10:
        return RedirectResponse("/journal?error=Kegiatan minimal 10 karakter.", status_code=status.HTTP_303_SEE_OTHER)

    journal = Journal(user_id=selected_user_id, kegiatan=kegiatan.strip(), output=output.strip())
    db.add(journal)
    db.flush()
    log_activity(db, current_user.id, "submit_journal", f"Jurnal: {kegiatan[:60]}")
    push_to_role(db, "pembimbing", f"Jurnal baru dari {current_user.username}: {kegiatan[:60]}")
    push_to_role(db, "admin", f"Jurnal baru dari {current_user.username}: {kegiatan[:60]}")
    db.commit()
    return RedirectResponse("/journal", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/journal/{journal_id}/sign")
def sign_journal_web(
    journal_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> object:
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if current_user.role not in {"admin", "pembimbing"}:
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    supervisor_profile = db.query(Supervisor).filter(Supervisor.user_id == current_user.id).first()
    if not supervisor_profile:
        return RedirectResponse(
            "/journal?error=Profil pembimbing belum tersedia. Lengkapi data pembimbing terlebih dahulu.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    journal = db.query(Journal).filter(Journal.id == journal_id).first()
    if not journal:
        return RedirectResponse("/journal?error=Jurnal tidak ditemukan.", status_code=status.HTTP_303_SEE_OTHER)

    signature_token = generate_journal_signature_token(journal.id, supervisor_profile.id)
    journal.signed_by_supervisor_id = supervisor_profile.id
    journal.signed_at = datetime.now()
    journal.signature_token = signature_token
    if journal.status in {"pending", "draft", "menunggu"}:
        journal.status = "approved"
    push_notification(db, journal.user_id, f"Jurnal Anda telah ditandatangani oleh {supervisor_profile.nama_lengkap}.", "success")
    db.commit()
    return RedirectResponse(
        "/journal?success=Jurnal berhasil ditandatangani pembimbing.",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/journal-signature/{token}")
def journal_signature_page(token: str, request: Request, db: Session = Depends(get_db)) -> object:
    try:
        journal_id, supervisor_id, issued_ts = verify_journal_signature_token(token)
    except ValueError:
        raise HTTPException(status_code=404, detail="Signature token tidak valid")

    journal = db.query(Journal).filter(Journal.id == journal_id).first()
    if not journal or journal.signature_token != token:
        raise HTTPException(status_code=404, detail="Data tanda tangan jurnal tidak ditemukan")

    supervisor = db.query(Supervisor).filter(Supervisor.id == supervisor_id).first()
    if not supervisor or journal.signed_by_supervisor_id != supervisor.id:
        raise HTTPException(status_code=404, detail="Identitas pembimbing tidak ditemukan")

    participant_name = journal.user.username if journal.user else f"User {journal.user_id}"
    issued_at = datetime.fromtimestamp(issued_ts)

    return templates.TemplateResponse(
        request,
        "journal_signature.html",
        {
            "request": request,
            "journal": journal,
            "supervisor": supervisor,
            "participant_name": participant_name,
            "issued_at": issued_at,
            "signed_at": journal.signed_at,
        },
    )


@router.post("/api/face/register")
@router.post("/face/register")
def register_face(payload: FacePayload, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    current_user = get_current_user(request, db)
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Silakan login terlebih dahulu")

    image_bytes = decode_base64_image(payload.image_base64)
    liveness = face_service.check_liveness(image_bytes)
    if not liveness["passed"]:
        raise HTTPException(
            status_code=400,
            detail="Registrasi ditolak karena wajah terlihat seperti foto atau layar. Gunakan wajah asli di depan kamera.",
        )
    try:
        result = face_service.register_embedding(image_bytes, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing = db.query(FaceEmbedding).filter(FaceEmbedding.user_id == current_user.id).first()
    embedding_json = serialize_embedding_for_storage(result["embedding"])
    thumbnail_encrypted = encrypt_text(result["thumbnail"]) if result.get("thumbnail") else None
    if existing:
        existing.embedding_json = embedding_json
        existing.thumbnail_encrypted = thumbnail_encrypted
    else:
        db.add(FaceEmbedding(user_id=current_user.id, embedding_json=embedding_json, thumbnail_encrypted=thumbnail_encrypted))
    db.commit()

    return {
        "message": "Registrasi wajah berhasil",
        "engine": result["engine"],
        "dim": result["dim"],
        "thumbnail": result.get("thumbnail"),
    }


@router.get("/api/face/thumbnail")
def get_face_thumbnail(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    current_user = get_current_user(request, db)
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Silakan login terlebih dahulu")

    stored = db.query(FaceEmbedding).filter(FaceEmbedding.user_id == current_user.id).first()
    if not stored or not stored.thumbnail_encrypted:
        return {"thumbnail": None}

    try:
        thumbnail = decrypt_text(stored.thumbnail_encrypted)
    except Exception:
        thumbnail = None
    return {"thumbnail": thumbnail}


@router.post("/api/face/verify")
@router.post("/face/verify")
def verify_face(payload: FacePayload, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    current_user = get_current_user(request, db)
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Silakan login terlebih dahulu")

    action = payload.action.lower().strip()
    if action not in {"checkin", "checkout"}:
        raise HTTPException(status_code=400, detail="Aksi absensi tidak valid")

    source_ip = get_client_ip(request)

    office_policy = resolve_effective_office_policy(db, current_user)
    if not office_policy:
        raise HTTPException(
            status_code=503,
            detail="Lokasi kantor belum dikonfigurasi admin. Hubungi admin untuk mengisi GPS kantor atau geofence instansi.",
        )
    if payload.latitude is None or payload.longitude is None:
        raise HTTPException(
            status_code=400,
            detail="GPS wajib aktif saat absensi. Izinkan akses lokasi lalu coba lagi.",
        )
    max_accuracy_m = int(office_policy["max_accuracy_m"])
    if payload.accuracy_m is None:
        raise HTTPException(
            status_code=400,
            detail="Akurasi GPS tidak terbaca. Tunggu sinyal GPS stabil lalu coba lagi.",
        )
    if payload.accuracy_m > max_accuracy_m:
        log_face_verification(
            db,
            user_id=current_user.id,
            action=action,
            matched=False,
            source_ip=source_ip,
            message=(
                f"Akurasi GPS terlalu rendah ({payload.accuracy_m:.1f}m > {max_accuracy_m}m)"
            ),
        )
        db.commit()
        raise HTTPException(
            status_code=400,
            detail=(
                f"Sinyal GPS perangkat Anda belum presisi (radius ketidakpastian ~{int(payload.accuracy_m)}m, "
                f"dibutuhkan di bawah {max_accuracy_m}m). Ini BUKAN berarti Anda jauh dari lokasi — "
                "GPS perangkat saja yang belum akurat. Coba: aktifkan 'Lokasi presisi/precise location' di HP, "
                "pindah ke area terbuka (bukan dalam gedung), tunggu 10-15 detik agar GPS terkunci, lalu coba lagi."
            ),
        )
    office_lat = float(office_policy["latitude"])
    office_lng = float(office_policy["longitude"])
    office_radius_m = int(office_policy["radius_m"])
    office_grace_m = int(office_policy["grace_m"])
    distance_m = haversine_distance_m(payload.latitude, payload.longitude, office_lat, office_lng)
    location_risk_detected, location_risk_message = detect_location_risk(
        db,
        user_id=current_user.id,
        now=datetime.now(),
        latitude=payload.latitude,
        longitude=payload.longitude,
    )
    is_within_grace = distance_m > office_radius_m and distance_m <= (office_radius_m + office_grace_m)
    review_reason = None
    if is_within_grace and location_risk_detected:
        review_reason = "grace_and_risk"
    elif is_within_grace:
        review_reason = "grace"
    elif location_risk_detected:
        review_reason = "risk"
    if distance_m > (office_radius_m + office_grace_m):
        log_face_verification(
            db,
            user_id=current_user.id,
            action=action,
            matched=False,
            source_ip=source_ip,
            message=(
                f"Di luar radius kantor ({distance_m:.1f}m > {office_radius_m}m + grace {office_grace_m}m)"
            ),
        )
        db.commit()
        raise HTTPException(
            status_code=403,
            detail=(
                f"Anda berada {int(distance_m)} meter dari kantor. "
                f"Batas absensi adalah {office_radius_m} meter "
                f"dengan toleransi {office_grace_m} meter."
            ),
        )

    if check_face_lock(db, current_user.id):
        log_face_verification(
            db,
            user_id=current_user.id,
            action=action,
            matched=False,
            source_ip=source_ip,
            attempt_blocked=True,
            message="Percobaan verifikasi diblokir sementara karena gagal beruntun",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Terlalu banyak verifikasi gagal. "
                f"Coba lagi dalam {settings.face_lock_minutes} menit."
            ),
        )

    stored = db.query(FaceEmbedding).filter(FaceEmbedding.user_id == current_user.id).first()
    if not stored:
        log_face_verification(
            db,
            user_id=current_user.id,
            action=action,
            matched=False,
            source_ip=source_ip,
            message="Wajah belum terdaftar",
        )
        db.commit()
        raise HTTPException(status_code=404, detail="Wajah belum terdaftar")

    try:
        stored_embedding, legacy_format = deserialize_embedding_from_storage(stored.embedding_json)
    except (ValueError, json.JSONDecodeError) as exc:
        log_face_verification(
            db,
            user_id=current_user.id,
            action=action,
            matched=False,
            source_ip=source_ip,
            message="Data embedding tersimpan tidak valid",
        )
        db.commit()
        raise HTTPException(status_code=500, detail="Data wajah tersimpan tidak valid") from exc

    if legacy_format:
        # Auto-migrate old plain JSON embeddings to encrypted format.
        stored.embedding_json = serialize_embedding_for_storage(stored_embedding)
        db.commit()

    image_bytes = decode_base64_image(payload.image_base64)

    liveness = face_service.check_liveness(image_bytes)
    if not liveness["passed"]:
        log_face_verification(
            db,
            user_id=current_user.id,
            action=action,
            matched=False,
            source_ip=source_ip,
            message=f"Liveness check gagal (score={liveness['score']})",
        )
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Terdeteksi kemungkinan foto atau layar. Pastikan wajah nyata di depan kamera.",
        )

    try:
        result = face_service.verify_embedding(image_bytes, stored_embedding)
    except ValueError as exc:
        log_face_verification(
            db,
            user_id=current_user.id,
            action=action,
            matched=False,
            source_ip=source_ip,
            message=str(exc),
        )
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not result["matched"]:
        log_face_verification(
            db,
            user_id=current_user.id,
            action=action,
            matched=False,
            source_ip=source_ip,
            similarity=result.get("similarity"),
            confidence=result.get("confidence"),
            engine=result.get("engine"),
            message=result.get("message"),
        )
        db.commit()
        raise HTTPException(status_code=401, detail=result["message"])

    now = datetime.now()
    today = now.date()
    attendance = (
        db.query(Attendance)
        .filter(Attendance.user_id == current_user.id)
        .filter(func.date(Attendance.attendance_date) == today)
        .order_by(Attendance.id.desc())
        .first()
    )

    if action == "checkin":
        if attendance and attendance.check_in_time is not None:
            raise HTTPException(status_code=400, detail="Anda sudah check-in hari ini")

        if not attendance:
            attendance = Attendance(
                user_id=current_user.id,
                check_in_time=now,
                status=calculate_status(now, db),
                confidence_score=result["confidence"],
                latitude=payload.latitude,
                longitude=payload.longitude,
                distance_from_office_m=distance_m,
                requires_location_review=is_within_grace or location_risk_detected,
                location_review_reason=review_reason,
                location_review_status="pending" if review_reason else "not_required",
                location_review_note=location_risk_message if location_risk_detected else None,
                location_reviewed_by_user_id=None,
                location_reviewed_at=None,
            )
            db.add(attendance)
        else:
            attendance.check_in_time = now
            attendance.status = calculate_status(now, db)
            attendance.confidence_score = result["confidence"]
            attendance.latitude = payload.latitude
            attendance.longitude = payload.longitude
            attendance.distance_from_office_m = distance_m
            attendance.requires_location_review = is_within_grace or location_risk_detected
            attendance.location_review_reason = review_reason
            attendance.location_review_status = "pending" if review_reason else "not_required"
            attendance.location_review_note = location_risk_message if location_risk_detected else None
            attendance.location_reviewed_by_user_id = None
            attendance.location_reviewed_at = None
    else:
        if not attendance or attendance.check_in_time is None:
            raise HTTPException(status_code=400, detail="Anda belum check-in hari ini")
        if attendance.check_out_time is not None:
            raise HTTPException(status_code=400, detail="Anda sudah check-out hari ini")

        attendance.check_out_time = now
        attendance.confidence_score = result["confidence"]
        attendance.latitude = payload.latitude
        attendance.longitude = payload.longitude
        attendance.distance_from_office_m = distance_m
        attendance.requires_location_review = is_within_grace or location_risk_detected
        attendance.location_review_reason = review_reason
        attendance.location_review_status = "pending" if review_reason else "not_required"
        attendance.location_review_note = location_risk_message if location_risk_detected else None
        attendance.location_reviewed_by_user_id = None
        attendance.location_reviewed_at = None

        # Tandai pulang cepat jika checkout sebelum jam pulang
        jam_pulang = get_jam_pulang(db)
        if now.time() < jam_pulang:
            attendance.alasan_pulang_cepat = payload.alasan or ""
            pulang_cepat = True
        else:
            pulang_cepat = False

    log_face_verification(
        db,
        user_id=current_user.id,
        action=action,
        matched=True,
        source_ip=source_ip,
        similarity=result.get("similarity"),
        confidence=result.get("confidence"),
        engine=result.get("engine"),
        message=(
            (result.get("message") or "ok")
            + (" | risiko lokasi" if location_risk_detected else "")
        ),
    )
    db.commit()
    resp = {
        "message": "Absensi berhasil",
        "action": action,
        "status": attendance.status,
        "confidence": result["confidence"],
        "engine": result["engine"],
        "timestamp": now.isoformat(),
        "distance_m": round(distance_m, 1),
        "office_radius_m": office_radius_m,
        "office_grace_m": office_grace_m,
        "location_review_required": is_within_grace or location_risk_detected,
        "location_risk_detected": location_risk_detected,
        "geofence_source": office_policy["source"],
    }
    if office_policy.get("institution_name"):
        resp["geofence_institution"] = office_policy["institution_name"]
    if is_within_grace:
        resp["message"] = "Absensi berhasil (di area grace, perlu review admin)"
    if location_risk_detected:
        resp["message"] = "Absensi berhasil, tetapi terdeteksi anomali lokasi (perlu review admin)"
        if location_risk_message:
            resp["location_risk_message"] = location_risk_message
    if action == "checkout" and pulang_cepat:
        resp["pulang_cepat"] = True
        resp["need_reason"] = not bool(attendance.alasan_pulang_cepat)
        if is_within_grace:
            resp["message"] = "Check-out berhasil (di area grace) — tercatat pulang sebelum jam pulang"
        elif location_risk_detected:
            resp["message"] = "Check-out berhasil, tetapi lokasi terdeteksi anomali — tercatat pulang sebelum jam pulang"
        else:
            resp["message"] = "Check-out berhasil — tercatat pulang sebelum jam pulang"
    return resp
