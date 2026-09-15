"""Opt new pairs into a shared active-claim window; leave old runs unchanged."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260907_0031"
down_revision: str | None = "20260907_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("product_experiments", sa.Column("max_active_jobs", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_product_experiments_active_jobs_range"),
        "product_experiments",
        "max_active_jobs IS NULL OR max_active_jobs BETWEEN 1 AND 64",
    )
    op.create_unique_constraint(
        "uq_product_experiments_id_tenant", "product_experiments", ["id", "tenant_id"]
    )
    op.add_column("evaluation_runs", sa.Column("product_experiment_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_evaluation_runs_product_experiment_tenant",
        "evaluation_runs",
        "product_experiments",
        ["product_experiment_id", "tenant_id"],
        ["id", "tenant_id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index(
        "ix_evaluation_runs_product_experiment", "evaluation_runs", ["product_experiment_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_evaluation_runs_product_experiment", table_name="evaluation_runs")
    op.drop_constraint(
        "fk_evaluation_runs_product_experiment_tenant", "evaluation_runs", type_="foreignkey"
    )
    op.drop_column("evaluation_runs", "product_experiment_id")
    op.drop_constraint("uq_product_experiments_id_tenant", "product_experiments", type_="unique")
    op.drop_constraint(
        op.f("ck_product_experiments_active_jobs_range"), "product_experiments", type_="check"
    )
    op.drop_column("product_experiments", "max_active_jobs")
