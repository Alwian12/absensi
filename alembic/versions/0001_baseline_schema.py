"""baseline schema + legacy compatibility columns

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-27

Brownfield baseline (audit finding F-19). This single revision is intentionally
**idempotent and non-destructive** so it is safe to run against any database:

* fresh database          -> creates all tables from the current models
* existing/upgraded DB    -> creates only missing tables, adds only missing columns
* already-migrated DB     -> no-ops

It replaces the previous unversioned ``patch_legacy_schema()`` raw DDL that ran
on every application start.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.database import Base
import app.models  # noqa: F401  (registers all models on Base.metadata)

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels = None
depends_on = None

# Columns added over time to pre-existing tables. Kept here so old databases
# converge without a manual step. (name, DDL type) — mirrors the former patch.
_LEGACY_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "jurnal": [
        ("signed_by_supervisor_id", "INTEGER NULL"),
        ("signed_at", "DATETIME NULL"),
        ("signature_token", "VARCHAR(255) NULL"),
    ],
    "pembimbing": [
        ("nip", "VARCHAR(50) NULL"),
        ("jabatan", "VARCHAR(120) NULL"),
    ],
    "instansi": [
        ("office_latitude", "FLOAT NULL"),
        ("office_longitude", "FLOAT NULL"),
        ("office_radius_m", "INTEGER NULL"),
        ("office_grace_m", "INTEGER NULL"),
        ("office_max_accuracy_m", "INTEGER NULL"),
    ],
    "peserta": [
        ("tanggal_mulai", "DATETIME NULL"),
        ("tanggal_selesai", "DATETIME NULL"),
    ],
    "users": [
        ("session_version", "INTEGER NOT NULL DEFAULT 1"),
        ("deleted_at", "DATETIME NULL"),
    ],
    "absensi": [
        ("alasan_pulang_cepat", "VARCHAR(500) NULL"),
        ("latitude", "FLOAT NULL"),
        ("longitude", "FLOAT NULL"),
        ("distance_from_office_m", "FLOAT NULL"),
        ("requires_location_review", "BOOLEAN NOT NULL DEFAULT 0"),
        ("location_review_reason", "VARCHAR(30) NULL"),
        ("location_review_status", "VARCHAR(20) NOT NULL DEFAULT 'not_required'"),
        ("location_review_note", "VARCHAR(300) NULL"),
        ("location_reviewed_by_user_id", "INTEGER NULL"),
        ("location_reviewed_at", "DATETIME NULL"),
    ],
    "permohonan_izin": [
        ("jenis", "VARCHAR(20) NOT NULL DEFAULT 'izin'"),
    ],
    "face_embeddings": [
        ("thumbnail_encrypted", "MEDIUMTEXT NULL"),
    ],
}


def _ensure_legacy_columns(bind: sa.engine.Connection) -> None:
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for table, columns in _LEGACY_COLUMNS.items():
        if table not in existing_tables:
            continue
        present = {col["name"] for col in inspector.get_columns(table)}
        for name, ddl_type in columns:
            if name not in present:
                bind.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"))


def upgrade() -> None:
    bind = op.get_bind()
    # create_all uses checkfirst=True → only missing tables are created.
    Base.metadata.create_all(bind=bind)
    _ensure_legacy_columns(bind)


def downgrade() -> None:
    # Non-destructive by policy (PRD): never drop tables or data automatically.
    pass
