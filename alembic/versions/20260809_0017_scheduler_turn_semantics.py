"""Rename tenant fair scheduling state to match reservation semantics."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260809_0017"
down_revision: str | None = "20260808_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_tenants_last_job_claimed_at", table_name="tenants")
    op.alter_column(
        "tenants",
        "last_job_claimed_at",
        new_column_name="last_scheduler_turn_at",
    )
    op.create_index(
        "ix_tenants_last_scheduler_turn_at",
        "tenants",
        ["last_scheduler_turn_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tenants_last_scheduler_turn_at", table_name="tenants")
    op.alter_column(
        "tenants",
        "last_scheduler_turn_at",
        new_column_name="last_job_claimed_at",
    )
    op.create_index(
        "ix_tenants_last_job_claimed_at",
        "tenants",
        ["last_job_claimed_at"],
    )
