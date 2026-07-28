"""Create the Phase 0 migration baseline.

Revision ID: 20260728_0001
Revises:
Create Date: 2026-07-28
"""

revision: str = "20260728_0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Establish an Alembic head without creating future domain tables."""


def downgrade() -> None:
    """Remove only the Alembic revision marker."""
