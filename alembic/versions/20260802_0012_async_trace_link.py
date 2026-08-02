"""Persist the Run creation traceparent for asynchronous span links.

Revision ID: 20260802_0012
Revises: 20260802_0011
Create Date: 2026-08-02
"""

import sqlalchemy as sa

from alembic import op

revision: str = "20260802_0012"
down_revision: str | None = "20260802_0011"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_runs",
        sa.Column("origin_traceparent", sa.String(length=55), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evaluation_runs", "origin_traceparent")
