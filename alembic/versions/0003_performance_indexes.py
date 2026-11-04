"""performance indexes for attendance, journal, notifications and logs

Revision ID: 0003_indexes
Revises: 0002_rate_limit
Create Date: 2026-10-27

Adds indexes on the columns used for filtering/sorting by the dashboards,
list pages and reports (audit finding F-21: missing indexes / N+1 risk).
Non-destructive: indexes only. Existing indexes are skipped.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003_indexes"
down_revision: str | None = "0002_rate_limit"
branch_labels = None
depends_on = None

# (index name, table, columns)
INDEXES: list[tuple[str, str, list[str]]] = [
    ("ix_absensi_user_date", "absensi", ["user_id", "attendance_date"]),
    ("ix_absensi_date", "absensi", ["attendance_date"]),
    ("ix_absensi_review_status", "absensi", ["location_review_status"]),
    ("ix_jurnal_user_tanggal", "jurnal", ["user_id", "tanggal"]),
    ("ix_jurnal_status", "jurnal", ["status"]),
    ("ix_face_logs_user_created", "face_verification_logs", ["user_id", "created_at"]),
    ("ix_face_logs_created", "face_verification_logs", ["created_at"]),
    ("ix_notifikasi_user_read", "notifikasi", ["user_id", "is_read"]),
    ("ix_activity_log_user_created", "activity_log", ["user_id", "created_at"]),
    ("ix_leave_user_tanggal", "permohonan_izin", ["user_id", "tanggal"]),
]


def _existing_indexes(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table)}


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _existing_tables()
    for name, table, columns in INDEXES:
        if table not in tables:
            continue
        if name in _existing_indexes(table):
            continue
        op.create_index(name, table, columns)


def downgrade() -> None:
    # Non-destructive by policy: indexes are left in place.
    pass
