"""Add tenant scheduling state for fair job claiming."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260808_0016"
down_revision: str | None = "20260808_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("last_job_claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_tenants_last_job_claimed_at",
        "tenants",
        ["last_job_claimed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tenants_last_job_claimed_at", table_name="tenants")
    op.drop_column("tenants", "last_job_claimed_at")
