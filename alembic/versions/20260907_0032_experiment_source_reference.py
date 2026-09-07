"""Retain tenant-owned raw experiment input references without inventing old provenance."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260907_0032"
down_revision: str | None = "20260907_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_experiments", sa.Column("source_artifact_reference_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_product_experiments_source_reference_tenant",
        "product_experiments",
        "artifact_references",
        ["source_artifact_reference_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_product_experiments_source_reference_tenant", "product_experiments", type_="foreignkey"
    )
    op.drop_column("product_experiments", "source_artifact_reference_id")
