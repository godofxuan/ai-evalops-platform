"""Add an explicit permission for creating human review tasks.

Revision ID: 20260802_0011
Revises: 20260802_0010
Create Date: 2026-08-02
"""

import sqlalchemy as sa

from alembic import op

revision: str = "20260802_0011"
down_revision: str | None = "20260802_0010"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column(
            "can_create_review_tasks",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "can_create_review_tasks")
