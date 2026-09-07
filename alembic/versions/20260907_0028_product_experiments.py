"""Add tenant-isolated product experiment control records without backfilling old Runs."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260907_0028"
down_revision: str | None = "20260822_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_experiments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("snapshot_json", postgresql.JSONB(), nullable=False),
        sa.Column("baseline_run_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_product_experiments_tenant_key"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["baseline_run_id", "tenant_id"],
            ["evaluation_runs.id", "evaluation_runs.tenant_id"],
            name="fk_product_experiments_baseline_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_run_id", "tenant_id"],
            ["evaluation_runs.id", "evaluation_runs.tenant_id"],
            name="fk_product_experiments_candidate_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by", "tenant_id"],
            ["api_keys.id", "api_keys.tenant_id"],
            name="fk_product_experiments_actor_tenant",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("baseline_run_id <> candidate_run_id", name="distinct_arms"),
        sa.CheckConstraint("version > 0", name="version_positive"),
    )
    op.create_index(
        "ix_product_experiments_tenant_created", "product_experiments", ["tenant_id", "created_at"]
    )
    op.execute("ALTER TABLE product_experiments ENABLE ROW LEVEL SECURITY")
    predicate = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    op.execute(
        "CREATE POLICY product_experiments_tenant_isolation ON product_experiments "
        f"USING ({predicate}) WITH CHECK ({predicate})"
    )


def downgrade() -> None:
    # Only use in isolated migration tests; existing production experiments require a forward fix.
    op.drop_table("product_experiments")
