"""Index published Outbox rows for bounded retention cleanup.

Revision ID: 20260803_0014
Revises: 20260802_0013
Create Date: 2026-08-03
"""

import sqlalchemy as sa

from alembic import op

revision: str = "20260803_0014"
down_revision: str | None = "20260802_0013"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index(
        "ix_progress_event_outbox_published_retention",
        "progress_event_outbox",
        ["published_at", "id"],
        unique=False,
        postgresql_where=sa.text("published_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_progress_event_outbox_published_retention",
        table_name="progress_event_outbox",
        postgresql_where=sa.text("published_at IS NOT NULL"),
    )
