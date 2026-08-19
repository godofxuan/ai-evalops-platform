"""Add audit records for object-store orphan reconciliation."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260820_0024"
down_revision: str | None = "20260820_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifact_reconciliation_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("blob_sha256", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("details_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_artifact_reconciliation_events"),
    )
    op.create_index(
        "ix_artifact_reconciliation_events_sha_created",
        "artifact_reconciliation_events",
        ["blob_sha256", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_artifact_reconciliation_events_sha_created",
        table_name="artifact_reconciliation_events",
    )
    op.drop_table("artifact_reconciliation_events")
