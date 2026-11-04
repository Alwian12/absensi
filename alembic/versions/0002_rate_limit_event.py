"""rate_limit_event table (audit finding F-22)

Revision ID: 0002_rate_limit
Revises: 0001_baseline
Create Date: 2026-10-27

Persists rate-limit hits so login/face throttling survives restarts and applies
across multiple worker processes. Non-destructive: only creates a new table.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0002_rate_limit"
down_revision: str | None = "0001_baseline"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return name in set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if _table_exists("rate_limit_event"):
        return
    op.create_table(
        "rate_limit_event",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("bucket_key", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_rate_limit_event_bucket_key", "rate_limit_event", ["bucket_key"])
    op.create_index("ix_rate_limit_event_created_at", "rate_limit_event", ["created_at"])


def downgrade() -> None:
    # Non-destructive by policy: rate-limit data is disposable, but we only drop
    # the table when explicitly requested via a new, approved revision.
    pass
