from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.authentication.jwt_handler import create_token, hash_password
from app.database import SessionLocal
from app.main import app
from app.models.attendance import Attendance
from app.models.user import User


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


def test_checkin_legacy_query_param_rejected() -> None:
    """The legacy backdoor (token in query string without biometric payload) must be rejected."""
    client = TestClient(app)
    user = _create_user(role="peserta")
    token = create_token(str(user.id), user.role)

    # Calling checkin with query param ?token=... and no body must fail
    response = client.post(f"/api/attendance/checkin?token={token}")
    # Must be 422 (Unprocessable Entity) or 400/401, not 200
    assert response.status_code in {400, 401, 422}


def test_checkin_requires_authentication() -> None:
    """Unauthenticated check-in attempt is rejected with 401."""
    client = TestClient(app)
    response = client.post(
        "/api/attendance/checkin",
        json={
            "image_base64": "A" * 64,
            "latitude": -6.2,
            "longitude": 106.8,
            "accuracy_m": 10.0,
        },
    )
    assert response.status_code == 401


def test_checkin_non_peserta_rejected() -> None:
    """Only peserta may invoke self check-in; admin/pembimbing are rejected with 403."""
    client = TestClient(app)
    admin = _create_user(role="admin")
    token = create_token(str(admin.id), admin.role)

    response = client.post(
        "/api/attendance/checkin",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "image_base64": "A" * 64,
            "latitude": -6.2,
            "longitude": 106.8,
            "accuracy_m": 10.0,
        },
    )
    assert response.status_code == 403


def test_manual_attendance_by_peserta_is_forbidden() -> None:
    """Peserta cannot record manual attendance."""
    client = TestClient(app)
    peserta = _create_user(role="peserta")
    token = create_token(str(peserta.id), peserta.role)

    response = client.post(
        "/api/attendance/manual",
        headers={"Authorization": f"Bearer {token}"},
        json={"user_id": peserta.id, "status": "hadir"},
    )
    assert response.status_code == 403


def test_manual_attendance_by_admin_and_prevent_duplicate() -> None:
    """Admin can record manual attendance, and repeated calls on same day update instead of duplicating."""
    client = TestClient(app)
    admin = _create_user(role="admin")
    peserta = _create_user(role="peserta")
    admin_token = create_token(str(admin.id), admin.role)

    # 1. First manual attendance creates record
    resp1 = client.post(
        "/api/attendance/manual",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"user_id": peserta.id, "status": "hadir"},
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    att_id = data1["attendance_id"]
    assert data1["status"] == "hadir"

    # 2. Second manual attendance updates the same day's record (no duplicate row)
    resp2 = client.post(
        "/api/attendance/manual",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"user_id": peserta.id, "status": "izin"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["attendance_id"] == att_id
    assert data2["status"] == "izin"

    # Verify directly in DB: exactly 1 attendance row for this user
    db = SessionLocal()
    try:
        count = db.query(Attendance).filter(Attendance.user_id == peserta.id).count()
        assert count == 1
    finally:
        db.close()


def test_history_role_isolation() -> None:
    """Peserta can only see their own attendance history."""
    client = TestClient(app)
    peserta1 = _create_user(role="peserta")
    peserta2 = _create_user(role="peserta")
    admin = _create_user(role="admin")

    db = SessionLocal()
    try:
        db.add(Attendance(user_id=peserta1.id, status="hadir", check_in_time=datetime.now()))
        db.add(Attendance(user_id=peserta2.id, status="terlambat", check_in_time=datetime.now()))
        db.commit()
    finally:
        db.close()

    token1 = create_token(str(peserta1.id), peserta1.role)
    admin_token = create_token(str(admin.id), admin.role)

    # Peserta 1 sees only their own
    resp1 = client.get("/api/attendance/history", headers={"Authorization": f"Bearer {token1}"})
    assert resp1.status_code == 200
    rows1 = resp1.json()
    assert len(rows1) >= 1
    assert all(r["user_id"] == peserta1.id for r in rows1)

    # Admin can filter by peserta2
    resp_admin = client.get(
        f"/api/attendance/history?user_id={peserta2.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_admin.status_code == 200
    rows_admin = resp_admin.json()
    assert len(rows_admin) >= 1
    assert all(r["user_id"] == peserta2.id for r in rows_admin)



def test_checkout_coordinates_do_not_overwrite_checkin_coordinates(monkeypatch) -> None:
    """Option B: Verification that check-out records its own coordinates without overwriting morning check-in coordinates."""
    import json
    from app.models.app_setting import AppSetting
    from app.models.face_embedding import FaceEmbedding
    from app.routers import web as web_router

    # Mock face_service methods so test doesn't require camera/models
    monkeypatch.setattr(
        web_router.face_service,
        "check_liveness",
        lambda _bytes: {"passed": True, "score": 25.0, "method": "test"},
    )
    monkeypatch.setattr(
        web_router.face_service,
        "verify_embedding",
        lambda _bytes, _emb, _threshold=None: {
            "matched": True,
            "similarity": 0.95,
            "confidence": 0.95,
            "engine": "test",
            "message": "Wajah cocok",
        },
    )

    client = TestClient(app)
    peserta = _create_user(role="peserta")
    token = create_token(str(peserta.id), peserta.role)

    # Configure office location and participant face embedding
    db = SessionLocal()
    try:
        def _set_setting(key, val):
            row = db.query(AppSetting).filter(AppSetting.key == key).first()
            if row:
                row.value = val
            else:
                db.add(AppSetting(key=key, value=val))

        _set_setting("office_latitude", "-6.2000000")
        _set_setting("office_longitude", "106.8000000")
        _set_setting("office_radius_m", "300")
        _set_setting("office_grace_m", "20")
        _set_setting("office_max_accuracy_m", "80")
        _set_setting("jam_pulang", "16:00")

        db.add(FaceEmbedding(user_id=peserta.id, embedding_json=json.dumps([0.1, 0.2, 0.3])))
        db.commit()
    finally:
        db.close()

    image_dummy = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAoMBgQmL9z8AAAAASUVORK5CYII="

    # 1. Check-in at Location A
    checkin_lat = -6.2001000
    checkin_lng = 106.8001000
    resp_in = client.post(
        "/api/attendance/checkin",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "image_base64": image_dummy,
            "latitude": checkin_lat,
            "longitude": checkin_lng,
            "accuracy_m": 12.0,
        },
    )
    assert resp_in.status_code == 200

    # Verify check-in coordinates stored in DB
    db = SessionLocal()
    try:
        att = db.query(Attendance).filter(Attendance.user_id == peserta.id).first()
        assert att is not None
        assert abs(att.latitude - checkin_lat) < 1e-5
        assert abs(att.longitude - checkin_lng) < 1e-5
        assert att.check_out_time is None
        assert att.check_out_latitude is None
        assert att.check_out_longitude is None
    finally:
        db.close()

    # 2. Check-out at Location B
    checkout_lat = -6.2003000
    checkout_lng = 106.8003000
    resp_out = client.post(
        "/api/attendance/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "image_base64": image_dummy,
            "latitude": checkout_lat,
            "longitude": checkout_lng,
            "accuracy_m": 14.0,
            "alasan": "Selesai jam kerja",
        },
    )
    assert resp_out.status_code == 200

    # 3. VERIFY OPTION B: Check-in coordinates are STILL Location A, and Checkout coordinates are Location B!
    db = SessionLocal()
    try:
        att = db.query(Attendance).filter(Attendance.user_id == peserta.id).first()
        assert att is not None
        # Morning check-in location was NOT overwritten!
        assert abs(att.latitude - checkin_lat) < 1e-5
        assert abs(att.longitude - checkin_lng) < 1e-5

        # Afternoon check-out location is separately preserved!
        assert att.check_out_time is not None
        assert att.check_out_latitude is not None
        assert abs(att.check_out_latitude - checkout_lat) < 1e-5
        assert abs(att.check_out_longitude - checkout_lng) < 1e-5
        assert att.check_out_distance_m is not None
    finally:
        db.close()

    # 4. History endpoint returns both locations
    resp_hist = client.get("/api/attendance/history", headers={"Authorization": f"Bearer {token}"})
    assert resp_hist.status_code == 200
    hist = resp_hist.json()
    assert len(hist) == 1
    assert abs(hist[0]["latitude"] - checkin_lat) < 1e-5
    assert abs(hist[0]["check_out_latitude"] - checkout_lat) < 1e-5
