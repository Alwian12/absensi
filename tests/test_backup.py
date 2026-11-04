from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from app.main import app
from app.models.user import User
from app.models.admin_audit_log import AdminAuditLog
from app.security.session import create_session_token, SESSION_COOKIE
from app.routers.admin import find_mysqldump, generate_mysql_dump_python
from app.database import get_db, SessionLocal


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def admin_user(db_session: Session):
    user = db_session.query(User).filter(User.username == "admin_backup_test").first()
    if not user:
        user = User(
            username="admin_backup_test",
            email="admin_backup_test@example.com",
            password_hash="fakehash",
            role="admin",
            is_active=True,
            session_version=1,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    return user


@pytest.fixture
def peserta_user(db_session: Session):
    user = db_session.query(User).filter(User.username == "peserta_backup_test").first()
    if not user:
        user = User(
            username="peserta_backup_test",
            email="peserta_backup_test@example.com",
            password_hash="fakehash",
            role="peserta",
            is_active=True,
            session_version=1,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    return user


def test_backup_unauthenticated_redirects_to_login():
    client = TestClient(app)
    response = client.get("/admin/backup", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == "/login"


def test_backup_non_admin_redirects_to_dashboard(peserta_user: User):
    client = TestClient(app)
    token = create_session_token(peserta_user.id, peserta_user.session_version or 1)
    client.cookies.set(SESSION_COOKIE, token)
    response = client.get("/admin/backup", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == "/dashboard"


def test_backup_sqlite_success(admin_user: User, db_session: Session):
    client = TestClient(app)
    token = create_session_token(admin_user.id, admin_user.session_version or 1)
    client.cookies.set(SESSION_COOKIE, token)

    response = client.get("/admin/backup")
    assert response.status_code == 200
    assert response.headers.get("content-type") == "application/octet-stream"
    disp = response.headers.get("content-disposition", "")
    assert "attachment; filename=backup-pkl-" in disp
    assert disp.endswith(".db")
    assert len(response.content) > 0

    # Verify audit log recorded
    log = (
        db_session.query(AdminAuditLog)
        .filter(AdminAuditLog.admin_user_id == admin_user.id, AdminAuditLog.action == "backup_database")
        .order_by(AdminAuditLog.id.desc())
        .first()
    )
    assert log is not None
    assert "SQLite" in (log.detail or "")


def test_find_mysqldump_detects_or_returns_none():
    res = find_mysqldump()
    # On this machine, Laragon's mysqldump.exe exists
    if res:
        assert "mysqldump" in res.lower()
        assert os.path.exists(res)


def test_backup_mysql_with_mysqldump(admin_user: User, db_session: Session):
    client = TestClient(app)
    token = create_session_token(admin_user.id, admin_user.session_version or 1)
    client.cookies.set(SESSION_COOKIE, token)

    dummy_sql_bytes = b"-- MySQL dump 10.13\nCREATE DATABASE absensi;\n"

    with patch("app.config.settings.database_url", "mysql://root:@localhost:3306/absensi"):
        with patch("app.routers.admin.find_mysqldump", return_value="C:\\laragon\\bin\\mysql\\bin\\mysqldump.exe"):
            with patch("app.routers.admin.stream_mysqldump_process", return_value=iter([dummy_sql_bytes])):
                response = client.get("/admin/backup")
                assert response.status_code == 200
                assert response.headers.get("content-type") == "application/sql"
                disp = response.headers.get("content-disposition", "")
                assert "attachment; filename=backup-pkl-" in disp
                assert disp.endswith(".sql")
                assert response.content == dummy_sql_bytes


def test_backup_mysql_fallback_python_generator(admin_user: User, db_session: Session):
    client = TestClient(app)
    token = create_session_token(admin_user.id, admin_user.session_version or 1)
    client.cookies.set(SESSION_COOKIE, token)

    with patch("app.config.settings.database_url", "mysql://root:@localhost:3306/absensi"):
        with patch("app.routers.admin.find_mysqldump", return_value=None):
            response = client.get("/admin/backup")
            assert response.status_code == 200
            assert response.headers.get("content-type") == "application/sql"
            disp = response.headers.get("content-disposition", "")
            assert "attachment; filename=backup-pkl-" in disp
            assert disp.endswith(".sql")
            content_str = response.content.decode("utf-8")
            assert "SET FOREIGN_KEY_CHECKS=0;" in content_str
            assert "SET FOREIGN_KEY_CHECKS=1;" in content_str


def test_generate_mysql_dump_python_yields_valid_sql(db_session: Session):
    generator = generate_mysql_dump_python(db_session, "test_db")
    chunks = list(generator)
    full_sql = b"".join(chunks).decode("utf-8")
    assert "-- Multi-Engine Database Backup" in full_sql
    assert "SET FOREIGN_KEY_CHECKS=0;" in full_sql
    assert "DROP TABLE IF EXISTS" in full_sql
    assert "SET FOREIGN_KEY_CHECKS=1;" in full_sql
