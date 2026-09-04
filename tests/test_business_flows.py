import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.authentication.jwt_handler import hash_password
from app.database import SessionLocal
from app.main import app
from app.models.activity_log import ActivityLog
from app.models.admin_audit_log import AdminAuditLog
from app.models.app_setting import AppSetting
from app.models.attendance import Attendance
from app.models.face_embedding import FaceEmbedding
from app.models.face_verification_log import FaceVerificationLog
from app.models.institution import Institution
from app.models.journal import Journal
from app.models.leave_request import LeaveRequest
from app.models.notification import Notification
from app.models.participant import Participant
from app.models.supervisor import Supervisor
from app.models.user import User
from app.routers import web as web_router
from app.security.csrf import generate_csrf_token
from app.services.scheduler import apply_automatic_absence_for_date


def _create_user(*, role: str) -> User:
    db = SessionLocal()
    try:
        suffix = uuid4().hex[:10]
        user = User(
            username=f"{role}_{suffix}",
            email=f"{role}_{suffix}@example.test",
            password_hash=hash_password("secret123"),
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _get_setting_value(db, key: str) -> str | None:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value if row else None


def _cleanup_users(user_ids: list[int]) -> None:
    db = SessionLocal()
    try:
        db.query(AdminAuditLog).filter(AdminAuditLog.admin_user_id.in_(user_ids)).delete(synchronize_session=False)
        db.query(AdminAuditLog).filter(AdminAuditLog.target_user_id.in_(user_ids)).delete(synchronize_session=False)
        db.query(ActivityLog).filter(ActivityLog.user_id.in_(user_ids)).delete(synchronize_session=False)
        db.query(Notification).filter(Notification.user_id.in_(user_ids)).delete(synchronize_session=False)
        db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def provide_csrf_for_form_posts(monkeypatch):
    original_post = TestClient.post

    def post_with_csrf(client, *args, **kwargs):
        if "json" not in kwargs:
            token = generate_csrf_token()
            client.cookies.set("csrf_token", token)
            form_data = dict(kwargs.get("data") or {})
            form_data.setdefault("csrf_token", token)
            kwargs["data"] = form_data
        return original_post(client, *args, **kwargs)

    monkeypatch.setattr(TestClient, "post", post_with_csrf)


def test_automatic_absence_creates_alpa_and_preserves_approved_leave() -> None:
    admin = _create_user(role="admin")
    peserta_alpa = _create_user(role="peserta")
    peserta_izin = _create_user(role="peserta")
    peserta_sakit = _create_user(role="peserta")
    target_date = datetime.now().date() + timedelta(days=2)
    after_checkout = datetime.combine(target_date, datetime.strptime("23:59", "%H:%M").time())

    db = SessionLocal()
    old_pulang = _get_setting_value(db, "jam_pulang")
    db.add(LeaveRequest(
        user_id=peserta_izin.id,
        jenis="izin",
        tanggal=after_checkout,
        keterangan="Izin keluarga",
        status="approved",
    ))
    db.add(LeaveRequest(
        user_id=peserta_sakit.id,
        jenis="sakit",
        tanggal=after_checkout,
        keterangan="Sakit demam",
        status="approved",
    ))
    row = db.query(AppSetting).filter(AppSetting.key == "jam_pulang").first()
    if row:
        row.value = "00:01"
    else:
        db.add(AppSetting(key="jam_pulang", value="00:01"))
    db.commit()
    db.close()

    try:
        db = SessionLocal()
        first_created = apply_automatic_absence_for_date(db, target_date, after_checkout)
        second_created = apply_automatic_absence_for_date(db, target_date, after_checkout)
        rows = db.query(Attendance).filter(Attendance.user_id.in_([
            peserta_alpa.id, peserta_izin.id, peserta_sakit.id,
        ])).all()
        statuses = {row.user_id: row.status for row in rows}
        counts = {user_id: sum(1 for row in rows if row.user_id == user_id) for user_id in statuses}
        db.close()

        assert first_created >= 3
        assert second_created == 0
        assert statuses[peserta_alpa.id] == "alpa"
        assert statuses[peserta_izin.id] == "izin"
        assert statuses[peserta_sakit.id] == "sakit"
        assert all(count == 1 for count in counts.values())
    finally:
        restore_db = SessionLocal()
        row = restore_db.query(AppSetting).filter(AppSetting.key == "jam_pulang").first()
        if row and old_pulang is not None:
            row.value = old_pulang
        restore_db.query(Attendance).filter(Attendance.user_id.in_([
            peserta_alpa.id, peserta_izin.id, peserta_sakit.id,
        ])).delete(synchronize_session=False)
        restore_db.query(LeaveRequest).filter(LeaveRequest.user_id.in_([
            peserta_alpa.id, peserta_izin.id, peserta_sakit.id,
        ])).delete(synchronize_session=False)
        restore_db.commit()
        restore_db.close()
        _cleanup_users([admin.id, peserta_alpa.id, peserta_izin.id, peserta_sakit.id])


def test_admin_can_update_attendance_settings() -> None:
    client = TestClient(app)
    admin = _create_user(role="admin")

    db = SessionLocal()
    old_masuk = _get_setting_value(db, "jam_masuk")
    old_pulang = _get_setting_value(db, "jam_pulang")
    old_auto_hide = _get_setting_value(db, "attendance_success_auto_hide_seconds")
    old_transition = _get_setting_value(db, "attendance_transition_style")
    db.close()

    try:
        client.cookies.set("user_id", str(admin.id))
        response = client.post(
            "/admin/attendance-settings",
            data={
                "jam_masuk": "07:30",
                "jam_pulang": "15:45",
                "success_auto_hide_seconds": "12",
                "transition_style": "slow",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers.get("location", "").startswith("/dashboard?success=")

        verify_db = SessionLocal()
        try:
            assert _get_setting_value(verify_db, "jam_masuk") == "07:30"
            assert _get_setting_value(verify_db, "jam_pulang") == "15:45"
            assert _get_setting_value(verify_db, "attendance_success_auto_hide_seconds") == "12"
            assert _get_setting_value(verify_db, "attendance_transition_style") == "slow"
        finally:
            verify_db.close()
    finally:
        restore_db = SessionLocal()
        try:
            if old_masuk is not None:
                row = restore_db.query(AppSetting).filter(AppSetting.key == "jam_masuk").first()
                if row:
                    row.value = old_masuk
            if old_pulang is not None:
                row = restore_db.query(AppSetting).filter(AppSetting.key == "jam_pulang").first()
                if row:
                    row.value = old_pulang
            if old_auto_hide is not None:
                row = restore_db.query(AppSetting).filter(AppSetting.key == "attendance_success_auto_hide_seconds").first()
                if row:
                    row.value = old_auto_hide
            if old_transition is not None:
                row = restore_db.query(AppSetting).filter(AppSetting.key == "attendance_transition_style").first()
                if row:
                    row.value = old_transition
            restore_db.commit()
        finally:
            restore_db.close()
        _cleanup_users([admin.id])


def test_admin_can_update_office_geofence() -> None:
    client = TestClient(app)
    admin = _create_user(role="admin")

    db = SessionLocal()
    old_office_lat = _get_setting_value(db, "office_latitude")
    old_office_lng = _get_setting_value(db, "office_longitude")
    old_office_radius = _get_setting_value(db, "office_radius_m")
    old_office_grace = _get_setting_value(db, "office_grace_m")
    old_office_max_accuracy = _get_setting_value(db, "office_max_accuracy_m")
    db.close()

    try:
        client.cookies.set("user_id", str(admin.id))
        response = client.post(
            "/admin/office-geofence",
            data={
                "office_latitude": "-6.2000000",
                "office_longitude": "106.8000000",
                "office_radius_m": "350",
                "office_grace_m": "20",
                "office_max_accuracy_m": "70",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers.get("location", "").startswith("/institutions?success=")

        verify_db = SessionLocal()
        try:
            assert _get_setting_value(verify_db, "office_latitude") == "-6.2000000"
            assert _get_setting_value(verify_db, "office_longitude") == "106.8000000"
            assert _get_setting_value(verify_db, "office_radius_m") == "350"
            assert _get_setting_value(verify_db, "office_grace_m") == "20"
            assert _get_setting_value(verify_db, "office_max_accuracy_m") == "70"
        finally:
            verify_db.close()
    finally:
        restore_db = SessionLocal()
        try:
            if old_office_lat is not None:
                row = restore_db.query(AppSetting).filter(AppSetting.key == "office_latitude").first()
                if row:
                    row.value = old_office_lat
            if old_office_lng is not None:
                row = restore_db.query(AppSetting).filter(AppSetting.key == "office_longitude").first()
                if row:
                    row.value = old_office_lng
            if old_office_radius is not None:
                row = restore_db.query(AppSetting).filter(AppSetting.key == "office_radius_m").first()
                if row:
                    row.value = old_office_radius
            if old_office_grace is not None:
                row = restore_db.query(AppSetting).filter(AppSetting.key == "office_grace_m").first()
                if row:
                    row.value = old_office_grace
            if old_office_max_accuracy is not None:
                row = restore_db.query(AppSetting).filter(AppSetting.key == "office_max_accuracy_m").first()
                if row:
                    row.value = old_office_max_accuracy
            restore_db.commit()
        finally:
            restore_db.close()
        _cleanup_users([admin.id])


def test_admin_attendance_settings_reject_invalid_time_format() -> None:
    client = TestClient(app)
    admin = _create_user(role="admin")

    try:
        client.cookies.set("user_id", str(admin.id))
        response = client.post(
            "/admin/attendance-settings",
            data={
                "jam_masuk": "xx:yy",
                "jam_pulang": "16:00",
                "success_auto_hide_seconds": "9",
                "transition_style": "normal",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers.get("location", "").startswith("/dashboard?error=")
    finally:
        _cleanup_users([admin.id])


def test_admin_attendance_settings_reject_invalid_time_order() -> None:
    client = TestClient(app)
    admin = _create_user(role="admin")

    try:
        client.cookies.set("user_id", str(admin.id))
        response = client.post(
            "/admin/attendance-settings",
            data={
                "jam_masuk": "17:00",
                "jam_pulang": "16:00",
                "success_auto_hide_seconds": "9",
                "transition_style": "normal",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers.get("location", "").startswith("/dashboard?error=")
    finally:
        _cleanup_users([admin.id])


def test_admin_attendance_settings_reject_invalid_transition_style() -> None:
    client = TestClient(app)
    admin = _create_user(role="admin")

    try:
        client.cookies.set("user_id", str(admin.id))
        response = client.post(
            "/admin/attendance-settings",
            data={
                "jam_masuk": "08:00",
                "jam_pulang": "16:00",
                "success_auto_hide_seconds": "9",
                "transition_style": "turbo",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers.get("location", "").startswith("/dashboard?error=")
    finally:
        _cleanup_users([admin.id])


def test_admin_attendance_settings_reject_invalid_auto_hide_range() -> None:
    client = TestClient(app)
    admin = _create_user(role="admin")

    try:
        client.cookies.set("user_id", str(admin.id))
        response = client.post(
            "/admin/attendance-settings",
            data={
                "jam_masuk": "08:00",
                "jam_pulang": "16:00",
                "success_auto_hide_seconds": "30",
                "transition_style": "normal",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers.get("location", "").startswith("/dashboard?error=")
    finally:
        _cleanup_users([admin.id])


def test_checkout_before_jam_pulang_stores_reason(monkeypatch) -> None:
    client = TestClient(app)
    peserta = _create_user(role="peserta")

    reason = "Izin urusan keluarga"
    image_payload = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAoMBgQmL9z8AAAAASUVORK5CYII="

    monkeypatch.setattr(
        web_router.face_service,
        "check_liveness",
        lambda _image: {"passed": True, "score": 0.99},
    )
    monkeypatch.setattr(
        web_router.face_service,
        "verify_embedding",
        lambda _image, _emb: {
            "matched": True,
            "similarity": 0.995,
            "confidence": 0.995,
            "engine": "test-engine",
            "message": "ok",
        },
    )

    db = SessionLocal()
    old_pulang = _get_setting_value(db, "jam_pulang")
    old_office_lat = _get_setting_value(db, "office_latitude")
    old_office_lng = _get_setting_value(db, "office_longitude")
    old_office_radius = _get_setting_value(db, "office_radius_m")
    old_office_grace = _get_setting_value(db, "office_grace_m")
    old_office_max_accuracy = _get_setting_value(db, "office_max_accuracy_m")
    face_embedding = FaceEmbedding(user_id=peserta.id, embedding_json=json.dumps([0.1, 0.2, 0.3]))
    db.add(face_embedding)
    setting_row = db.query(AppSetting).filter(AppSetting.key == "jam_pulang").first()
    if setting_row:
        setting_row.value = "23:59"
    else:
        db.add(AppSetting(key="jam_pulang", value="23:59"))
    office_lat_row = db.query(AppSetting).filter(AppSetting.key == "office_latitude").first()
    if office_lat_row:
        office_lat_row.value = "-6.2000000"
    else:
        db.add(AppSetting(key="office_latitude", value="-6.2000000"))
    office_lng_row = db.query(AppSetting).filter(AppSetting.key == "office_longitude").first()
    if office_lng_row:
        office_lng_row.value = "106.8000000"
    else:
        db.add(AppSetting(key="office_longitude", value="106.8000000"))
    office_radius_row = db.query(AppSetting).filter(AppSetting.key == "office_radius_m").first()
    if office_radius_row:
        office_radius_row.value = "250"
    else:
        db.add(AppSetting(key="office_radius_m", value="250"))
    office_grace_row = db.query(AppSetting).filter(AppSetting.key == "office_grace_m").first()
    if office_grace_row:
        office_grace_row.value = "15"
    else:
        db.add(AppSetting(key="office_grace_m", value="15"))
    office_max_accuracy_row = db.query(AppSetting).filter(AppSetting.key == "office_max_accuracy_m").first()
    if office_max_accuracy_row:
        office_max_accuracy_row.value = "80"
    else:
        db.add(AppSetting(key="office_max_accuracy_m", value="80"))
    db.commit()
    db.close()

    try:
        client.cookies.set("user_id", str(peserta.id))

        checkin_resp = client.post(
            "/api/face/verify",
            json={"image_base64": image_payload, "action": "checkin", "latitude": -6.2, "longitude": 106.8, "accuracy_m": 15},
        )
        assert checkin_resp.status_code == 200

        checkout_resp = client.post(
            "/api/face/verify",
            json={
                "image_base64": image_payload,
                "action": "checkout",
                "alasan": reason,
                "latitude": -6.2,
                "longitude": 106.8,
                "accuracy_m": 15,
            },
        )
        assert checkout_resp.status_code == 200

        payload = checkout_resp.json()
        assert payload.get("pulang_cepat") is True
        assert payload.get("need_reason") is False

        verify_db = SessionLocal()
        try:
            attendance = (
                verify_db.query(Attendance)
                .filter(Attendance.user_id == peserta.id)
                .order_by(Attendance.id.desc())
                .first()
            )
            assert attendance is not None
            assert attendance.alasan_pulang_cepat == reason
        finally:
            verify_db.close()
    finally:
        cleanup_db = SessionLocal()
        try:
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "jam_pulang").first()
            if row and old_pulang is not None:
                row.value = old_pulang
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_latitude").first()
            if row and old_office_lat is not None:
                row.value = old_office_lat
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_longitude").first()
            if row and old_office_lng is not None:
                row.value = old_office_lng
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_radius_m").first()
            if row and old_office_radius is not None:
                row.value = old_office_radius
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_grace_m").first()
            if row and old_office_grace is not None:
                row.value = old_office_grace
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_max_accuracy_m").first()
            if row and old_office_max_accuracy is not None:
                row.value = old_office_max_accuracy
            cleanup_db.query(FaceVerificationLog).filter(FaceVerificationLog.user_id == peserta.id).delete()
            cleanup_db.query(Attendance).filter(Attendance.user_id == peserta.id).delete()
            cleanup_db.query(FaceEmbedding).filter(FaceEmbedding.user_id == peserta.id).delete()
            cleanup_db.query(User).filter(User.id == peserta.id).delete()
            cleanup_db.commit()
        finally:
            cleanup_db.close()


def test_face_verify_rejects_when_outside_office_radius(monkeypatch) -> None:
    client = TestClient(app)
    peserta = _create_user(role="peserta")

    image_payload = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAoMBgQmL9z8AAAAASUVORK5CYII="

    monkeypatch.setattr(
        web_router.face_service,
        "check_liveness",
        lambda _image: {"passed": True, "score": 0.99},
    )
    monkeypatch.setattr(
        web_router.face_service,
        "verify_embedding",
        lambda _image, _emb: {
            "matched": True,
            "similarity": 0.995,
            "confidence": 0.995,
            "engine": "test-engine",
            "message": "ok",
        },
    )

    db = SessionLocal()
    old_office_lat = _get_setting_value(db, "office_latitude")
    old_office_lng = _get_setting_value(db, "office_longitude")
    old_office_radius = _get_setting_value(db, "office_radius_m")
    old_office_grace = _get_setting_value(db, "office_grace_m")
    old_office_max_accuracy = _get_setting_value(db, "office_max_accuracy_m")
    db.add(FaceEmbedding(user_id=peserta.id, embedding_json=json.dumps([0.1, 0.2, 0.3])))

    for key, value in {
        "office_latitude": "-6.2000000",
        "office_longitude": "106.8000000",
        "office_radius_m": "100",
        "office_grace_m": "0",
        "office_max_accuracy_m": "80",
    }.items():
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value))

    db.commit()
    db.close()

    try:
        client.cookies.set("user_id", str(peserta.id))
        response = client.post(
            "/api/face/verify",
            json={
                "image_base64": image_payload,
                "action": "checkin",
                "latitude": -6.2400000,
                "longitude": 106.8600000,
                "accuracy_m": 12,
            },
        )
        assert response.status_code == 403
    finally:
        cleanup_db = SessionLocal()
        try:
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_latitude").first()
            if row and old_office_lat is not None:
                row.value = old_office_lat
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_longitude").first()
            if row and old_office_lng is not None:
                row.value = old_office_lng
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_radius_m").first()
            if row and old_office_radius is not None:
                row.value = old_office_radius
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_grace_m").first()
            if row and old_office_grace is not None:
                row.value = old_office_grace
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_max_accuracy_m").first()
            if row and old_office_max_accuracy is not None:
                row.value = old_office_max_accuracy
            cleanup_db.query(FaceVerificationLog).filter(FaceVerificationLog.user_id == peserta.id).delete()
            cleanup_db.query(Attendance).filter(Attendance.user_id == peserta.id).delete()
            cleanup_db.query(FaceEmbedding).filter(FaceEmbedding.user_id == peserta.id).delete()
            cleanup_db.query(User).filter(User.id == peserta.id).delete()
            cleanup_db.commit()
        finally:
            cleanup_db.close()


def test_face_verify_rejects_when_gps_accuracy_too_low(monkeypatch) -> None:
    client = TestClient(app)
    peserta = _create_user(role="peserta")

    image_payload = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAoMBgQmL9z8AAAAASUVORK5CYII="

    monkeypatch.setattr(
        web_router.face_service,
        "check_liveness",
        lambda _image: {"passed": True, "score": 0.99},
    )
    monkeypatch.setattr(
        web_router.face_service,
        "verify_embedding",
        lambda _image, _emb: {
            "matched": True,
            "similarity": 0.995,
            "confidence": 0.995,
            "engine": "test-engine",
            "message": "ok",
        },
    )

    db = SessionLocal()
    old_office_lat = _get_setting_value(db, "office_latitude")
    old_office_lng = _get_setting_value(db, "office_longitude")
    old_office_radius = _get_setting_value(db, "office_radius_m")
    old_office_grace = _get_setting_value(db, "office_grace_m")
    old_office_max_accuracy = _get_setting_value(db, "office_max_accuracy_m")
    db.add(FaceEmbedding(user_id=peserta.id, embedding_json=json.dumps([0.1, 0.2, 0.3])))

    for key, value in {
        "office_latitude": "-6.2000000",
        "office_longitude": "106.8000000",
        "office_radius_m": "200",
        "office_grace_m": "10",
        "office_max_accuracy_m": "50",
    }.items():
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value))

    db.commit()
    db.close()

    try:
        client.cookies.set("user_id", str(peserta.id))
        response = client.post(
            "/api/face/verify",
            json={
                "image_base64": image_payload,
                "action": "checkin",
                "latitude": -6.2000000,
                "longitude": 106.8000000,
                "accuracy_m": 120,
            },
        )
        assert response.status_code == 400
        assert "presisi" in response.text
    finally:
        cleanup_db = SessionLocal()
        try:
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_latitude").first()
            if row and old_office_lat is not None:
                row.value = old_office_lat
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_longitude").first()
            if row and old_office_lng is not None:
                row.value = old_office_lng
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_radius_m").first()
            if row and old_office_radius is not None:
                row.value = old_office_radius
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_grace_m").first()
            if row and old_office_grace is not None:
                row.value = old_office_grace
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_max_accuracy_m").first()
            if row and old_office_max_accuracy is not None:
                row.value = old_office_max_accuracy
            cleanup_db.query(FaceVerificationLog).filter(FaceVerificationLog.user_id == peserta.id).delete()
            cleanup_db.query(Attendance).filter(Attendance.user_id == peserta.id).delete()
            cleanup_db.query(FaceEmbedding).filter(FaceEmbedding.user_id == peserta.id).delete()
            cleanup_db.query(User).filter(User.id == peserta.id).delete()
            cleanup_db.commit()
        finally:
            cleanup_db.close()


def test_face_verify_within_grace_marks_review(monkeypatch) -> None:
    client = TestClient(app)
    peserta = _create_user(role="peserta")

    image_payload = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAoMBgQmL9z8AAAAASUVORK5CYII="

    monkeypatch.setattr(
        web_router.face_service,
        "check_liveness",
        lambda _image: {"passed": True, "score": 0.99},
    )
    monkeypatch.setattr(
        web_router.face_service,
        "verify_embedding",
        lambda _image, _emb: {
            "matched": True,
            "similarity": 0.995,
            "confidence": 0.995,
            "engine": "test-engine",
            "message": "ok",
        },
    )

    db = SessionLocal()
    old_office_lat = _get_setting_value(db, "office_latitude")
    old_office_lng = _get_setting_value(db, "office_longitude")
    old_office_radius = _get_setting_value(db, "office_radius_m")
    old_office_grace = _get_setting_value(db, "office_grace_m")
    old_office_max_accuracy = _get_setting_value(db, "office_max_accuracy_m")
    db.add(FaceEmbedding(user_id=peserta.id, embedding_json=json.dumps([0.1, 0.2, 0.3])))

    for key, value in {
        "office_latitude": "-6.2000000",
        "office_longitude": "106.8000000",
        "office_radius_m": "100",
        "office_grace_m": "200",
        "office_max_accuracy_m": "80",
    }.items():
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value))

    db.commit()
    db.close()

    try:
        client.cookies.set("user_id", str(peserta.id))
        response = client.post(
            "/api/face/verify",
            json={
                "image_base64": image_payload,
                "action": "checkin",
                "latitude": -6.2010000,
                "longitude": 106.8017000,
                "accuracy_m": 20,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload.get("location_review_required") is True

        verify_db = SessionLocal()
        try:
            attendance = (
                verify_db.query(Attendance)
                .filter(Attendance.user_id == peserta.id)
                .order_by(Attendance.id.desc())
                .first()
            )
            assert attendance is not None
            assert attendance.requires_location_review is True
        finally:
            verify_db.close()
    finally:
        cleanup_db = SessionLocal()
        try:
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_latitude").first()
            if row and old_office_lat is not None:
                row.value = old_office_lat
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_longitude").first()
            if row and old_office_lng is not None:
                row.value = old_office_lng
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_radius_m").first()
            if row and old_office_radius is not None:
                row.value = old_office_radius
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_grace_m").first()
            if row and old_office_grace is not None:
                row.value = old_office_grace
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_max_accuracy_m").first()
            if row and old_office_max_accuracy is not None:
                row.value = old_office_max_accuracy
            cleanup_db.query(FaceVerificationLog).filter(FaceVerificationLog.user_id == peserta.id).delete()
            cleanup_db.query(Attendance).filter(Attendance.user_id == peserta.id).delete()
            cleanup_db.query(FaceEmbedding).filter(FaceEmbedding.user_id == peserta.id).delete()
            cleanup_db.query(User).filter(User.id == peserta.id).delete()
            cleanup_db.commit()
        finally:
            cleanup_db.close()


def test_face_verify_uses_institution_geofence_override(monkeypatch) -> None:
    client = TestClient(app)
    peserta = _create_user(role="peserta")

    image_payload = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAoMBgQmL9z8AAAAASUVORK5CYII="

    monkeypatch.setattr(
        web_router.face_service,
        "check_liveness",
        lambda _image: {"passed": True, "score": 0.99},
    )
    monkeypatch.setattr(
        web_router.face_service,
        "verify_embedding",
        lambda _image, _emb: {
            "matched": True,
            "similarity": 0.995,
            "confidence": 0.995,
            "engine": "test-engine",
            "message": "ok",
        },
    )

    db = SessionLocal()
    db.add(FaceEmbedding(user_id=peserta.id, embedding_json=json.dumps([0.1, 0.2, 0.3])))
    institution = Institution(
        nama_instansi="Instansi Geofence A",
        alamat="Alamat A",
        kontak="0812",
        office_latitude=-6.2010000,
        office_longitude=106.8010000,
        office_radius_m=250,
        office_grace_m=20,
        office_max_accuracy_m=70,
    )
    db.add(institution)
    db.flush()

    db.add(
        Participant(
            user_id=peserta.id,
            nama_lengkap="Peserta Test",
            jurusan="RPL",
            instansi="Instansi Geofence A",
        )
    )
    db.commit()
    inst_id = institution.id
    db.close()

    try:
        client.cookies.set("user_id", str(peserta.id))
        response = client.post(
            "/api/face/verify",
            json={
                "image_base64": image_payload,
                "action": "checkin",
                "latitude": -6.2010500,
                "longitude": 106.8010100,
                "accuracy_m": 12,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload.get("geofence_source") == "institution"
        assert payload.get("geofence_institution") == "Instansi Geofence A"
    finally:
        cleanup_db = SessionLocal()
        try:
            cleanup_db.query(FaceVerificationLog).filter(FaceVerificationLog.user_id == peserta.id).delete()
            cleanup_db.query(Attendance).filter(Attendance.user_id == peserta.id).delete()
            cleanup_db.query(FaceEmbedding).filter(FaceEmbedding.user_id == peserta.id).delete()
            cleanup_db.query(Participant).filter(Participant.user_id == peserta.id).delete()
            cleanup_db.query(Institution).filter(Institution.id == inst_id).delete()
            cleanup_db.query(User).filter(User.id == peserta.id).delete()
            cleanup_db.commit()
        finally:
            cleanup_db.close()


def test_face_verify_flags_location_risk_for_impossible_jump(monkeypatch) -> None:
    client = TestClient(app)
    peserta = _create_user(role="peserta")

    image_payload = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAoMBgQmL9z8AAAAASUVORK5CYII="

    monkeypatch.setattr(
        web_router.face_service,
        "check_liveness",
        lambda _image: {"passed": True, "score": 0.99},
    )
    monkeypatch.setattr(
        web_router.face_service,
        "verify_embedding",
        lambda _image, _emb: {
            "matched": True,
            "similarity": 0.995,
            "confidence": 0.995,
            "engine": "test-engine",
            "message": "ok",
        },
    )

    db = SessionLocal()
    old_office_lat = _get_setting_value(db, "office_latitude")
    old_office_lng = _get_setting_value(db, "office_longitude")
    old_office_radius = _get_setting_value(db, "office_radius_m")
    old_office_grace = _get_setting_value(db, "office_grace_m")
    old_office_max_accuracy = _get_setting_value(db, "office_max_accuracy_m")

    db.add(FaceEmbedding(user_id=peserta.id, embedding_json=json.dumps([0.1, 0.2, 0.3])))
    db.add(
        Attendance(
            user_id=peserta.id,
            attendance_date=datetime.now() - timedelta(minutes=1),
            check_in_time=datetime.now() - timedelta(minutes=1),
            status="hadir",
            latitude=-6.5000000,
            longitude=107.2000000,
            distance_from_office_m=1000,
        )
    )

    for key, value in {
        "office_latitude": "-6.2000000",
        "office_longitude": "106.8000000",
        "office_radius_m": "1500",
        "office_grace_m": "30",
        "office_max_accuracy_m": "80",
    }.items():
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value))

    db.commit()
    db.close()

    try:
        client.cookies.set("user_id", str(peserta.id))
        response = client.post(
            "/api/face/verify",
            json={
                "image_base64": image_payload,
                "action": "checkout",
                "alasan": "Uji anomali lokasi",
                "latitude": -6.2001000,
                "longitude": 106.8001000,
                "accuracy_m": 15,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload.get("location_risk_detected") is True
        assert payload.get("location_review_required") is True
    finally:
        cleanup_db = SessionLocal()
        try:
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_latitude").first()
            if row and old_office_lat is not None:
                row.value = old_office_lat
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_longitude").first()
            if row and old_office_lng is not None:
                row.value = old_office_lng
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_radius_m").first()
            if row and old_office_radius is not None:
                row.value = old_office_radius
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_grace_m").first()
            if row and old_office_grace is not None:
                row.value = old_office_grace
            row = cleanup_db.query(AppSetting).filter(AppSetting.key == "office_max_accuracy_m").first()
            if row and old_office_max_accuracy is not None:
                row.value = old_office_max_accuracy
            cleanup_db.query(FaceVerificationLog).filter(FaceVerificationLog.user_id == peserta.id).delete()
            cleanup_db.query(Attendance).filter(Attendance.user_id == peserta.id).delete()
            cleanup_db.query(FaceEmbedding).filter(FaceEmbedding.user_id == peserta.id).delete()
            cleanup_db.query(User).filter(User.id == peserta.id).delete()
            cleanup_db.commit()
        finally:
            cleanup_db.close()


def test_admin_can_approve_and_reject_location_review_status() -> None:
    client = TestClient(app)
    admin = _create_user(role="admin")
    peserta = _create_user(role="peserta")

    db = SessionLocal()
    attendance = Attendance(
        user_id=peserta.id,
        status="hadir",
        requires_location_review=True,
        location_review_reason="grace",
        location_review_status="pending",
    )
    db.add(attendance)
    db.commit()
    db.refresh(attendance)
    attendance_id = attendance.id
    db.close()

    try:
        client.cookies.set("user_id", str(admin.id))

        approve_resp = client.post(
            f"/attendance/{attendance_id}/location-review",
            data={"decision": "approved", "note": "Lokasi masih bisa ditoleransi"},
            follow_redirects=False,
        )
        assert approve_resp.status_code == 303

        verify_db = SessionLocal()
        try:
            row = verify_db.query(Attendance).filter(Attendance.id == attendance_id).first()
            assert row is not None
            assert row.location_review_status == "approved"
            assert row.location_review_note == "Lokasi masih bisa ditoleransi"
            assert row.location_reviewed_by_user_id == admin.id
            assert row.location_reviewed_at is not None
        finally:
            verify_db.close()

        reject_resp = client.post(
            f"/attendance/{attendance_id}/location-review",
            data={"decision": "rejected", "note": "Tidak valid"},
            follow_redirects=False,
        )
        assert reject_resp.status_code == 303

        verify_db = SessionLocal()
        try:
            row = verify_db.query(Attendance).filter(Attendance.id == attendance_id).first()
            assert row is not None
            assert row.location_review_status == "rejected"
            assert row.location_review_note == "Tidak valid"
            assert row.location_reviewed_by_user_id == admin.id
            assert row.location_reviewed_at is not None
        finally:
            verify_db.close()

        reset_resp = client.post(
            f"/attendance/{attendance_id}/location-review",
            data={"decision": "reset", "note": ""},
            follow_redirects=False,
        )
        assert reset_resp.status_code == 303

        verify_db = SessionLocal()
        try:
            row = verify_db.query(Attendance).filter(Attendance.id == attendance_id).first()
            assert row is not None
            assert row.location_review_status == "pending"
            assert row.location_review_note is None
            assert row.location_reviewed_by_user_id is None
            assert row.location_reviewed_at is None
        finally:
            verify_db.close()
    finally:
        cleanup_db = SessionLocal()
        try:
            cleanup_db.query(Attendance).filter(Attendance.id == attendance_id).delete()
            cleanup_db.commit()
        finally:
            cleanup_db.close()
        _cleanup_users([admin.id, peserta.id])


def test_journal_signature_sign_and_verify_page() -> None:
    client = TestClient(app)
    pembimbing = _create_user(role="pembimbing")
    peserta = _create_user(role="peserta")

    db = SessionLocal()
    supervisor = Supervisor(
        user_id=pembimbing.id,
        nama_lengkap="Pembimbing Test",
        nip="19880011",
        jabatan="Koordinator PKL",
        bidang="Teknis",
    )
    db.add(supervisor)
    db.flush()

    journal = Journal(
        user_id=peserta.id,
        kegiatan="Mengerjakan pengujian sistem absensi dan validasi data.",
        output="Laporan uji internal",
        status="pending",
    )
    db.add(journal)
    db.commit()
    db.refresh(journal)
    supervisor_id = supervisor.id
    db.close()

    try:
        client.cookies.set("user_id", str(pembimbing.id))
        sign_resp = client.post(f"/journal/{journal.id}/sign", follow_redirects=False)
        assert sign_resp.status_code == 303
        assert sign_resp.headers.get("location", "").startswith("/journal?success=")

        verify_db = SessionLocal()
        try:
            signed_journal = verify_db.query(Journal).filter(Journal.id == journal.id).first()
            assert signed_journal is not None
            assert signed_journal.signature_token is not None
            assert signed_journal.signed_by_supervisor_id == supervisor_id
            assert signed_journal.status == "approved"

            token = signed_journal.signature_token
        finally:
            verify_db.close()

        verify_page = client.get(f"/journal-signature/{token}")
        assert verify_page.status_code == 200
        assert "text/html" in verify_page.headers.get("content-type", "")
        assert "Pembimbing Test" in verify_page.text
        assert "19880011" in verify_page.text
        assert "Koordinator PKL" in verify_page.text
    finally:
        cleanup_db = SessionLocal()
        try:
            cleanup_db.query(Notification).filter(Notification.user_id.in_([pembimbing.id, peserta.id])).delete(synchronize_session=False)
            cleanup_db.query(Journal).filter(Journal.user_id == peserta.id).delete(synchronize_session=False)
            cleanup_db.query(Supervisor).filter(Supervisor.user_id == pembimbing.id).delete(synchronize_session=False)
            cleanup_db.commit()
        finally:
            cleanup_db.close()
        _cleanup_users([pembimbing.id, peserta.id])


def test_admin_reset_password_updates_target_password() -> None:
    client = TestClient(app)
    admin = _create_user(role="admin")
    target = _create_user(role="peserta")

    try:
        client.cookies.set("user_id", str(admin.id))
        response = client.post(
            f"/users/{target.id}/password",
            data={"new_password": "newsecret123", "redirect_to": "/dashboard"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers.get("location", "").startswith("/dashboard?success=")

        verify_db = SessionLocal()
        try:
            updated_target = verify_db.query(User).filter(User.id == target.id).first()
            assert updated_target is not None
            assert updated_target.password_hash != target.password_hash
        finally:
            verify_db.close()
    finally:
        _cleanup_users([admin.id, target.id])


def test_admin_force_logout_invalidates_existing_session_version_cookie() -> None:
    admin_client = TestClient(app)
    user_client = TestClient(app)

    admin = _create_user(role="admin")
    target = _create_user(role="peserta")
    old_session_ver = target.session_version or 1

    try:
        user_client.cookies.set("user_id", str(target.id))
        user_client.cookies.set("session_ver", str(old_session_ver))
        before = user_client.get("/dashboard", follow_redirects=False)
        assert before.status_code == 200

        admin_client.cookies.set("user_id", str(admin.id))
        force_resp = admin_client.post(
            f"/users/{target.id}/force-logout",
            data={"redirect_to": "/dashboard"},
            follow_redirects=False,
        )
        assert force_resp.status_code == 303
        assert force_resp.headers.get("location", "").startswith("/dashboard?success=")

        after = user_client.get("/dashboard", follow_redirects=False)
        assert after.status_code == 303
        assert after.headers.get("location") == "/login"
    finally:
        _cleanup_users([admin.id, target.id])
