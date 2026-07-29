"""Expand the artifact type column for human review packets.

Revision ID: 20260729_0008
Revises: 20260729_0007
Create Date: 2026-07-29
"""

import sqlalchemy as sa

from alembic import op

revision: str = "20260729_0008"
down_revision: str | None = "20260729_0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column(
        "artifacts",
        "artifact_type",
        existing_type=sa.String(length=14),
        type_=sa.String(length=32),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Phase 8 already permits the 19-character "human_review_packet" value.
    # Shrinking back to VARCHAR(14) would recreate the defect and could reject
    # existing packet metadata, so the safe widening intentionally remains.
    pass
