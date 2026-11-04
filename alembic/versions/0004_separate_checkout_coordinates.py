"""separate checkout coordinates for attendance records

Revision ID: 0004_checkout_coords
Revises: 0003_indexes
Create Date: 2026-11-02

Adds dedicated check-out location columns to the 'absensi' table so that checking out
in the afternoon does not overwrite the morning check-in coordinates.
Non-destructive: existing columns and data are preserved.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004_checkout_coords"
down_revision: str | None = "0003_indexes"
branch_labels = None
depends_on = None

NEW_COLUMNS: list[tuple[str, sa.types.TypeEngine, bool, object]] = [
    ("check_out_latitude", sa.Float(), True, None),
    ("check_out_longitude", sa.Float(), True, None),
    ("check_out_distance_m", sa.Float(), True, None),
    ("check_out_requires_location_review", sa.Boolean(), False, False),
    ("check_out_location_review_reason", sa.String(30), True, None),
    ("check_out_location_review_status", sa.String(20), False, "not_required"),
    ("check_out_location_review_note", sa.String(300), True, None),
]


def _existing_columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    columns = _existing_columns("absensi")
    for col_name, col_type, nullable, default in NEW_COLUMNS:
        if col_name not in columns:
            server_default = None
            if isinstance(default, str):
                server_default = sa.text(f"'{default}'")
            elif default is False:
                server_default = sa.text("0")
            elif default is True:
                server_default = sa.text("1")

            op.add_column(
                "absensi",
                sa.Column(
                    col_name,
                    col_type,
                    nullable=nullable,
                    server_default=server_default,
                ),
            )


def downgrade() -> None:
    # Non-destructive by policy: columns are left in place.
    pass

