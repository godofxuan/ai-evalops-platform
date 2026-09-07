"""Bind immutable experiment reports to tenant-owned content-addressed artifacts."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260907_0033"
down_revision: str | None = "20260907_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TYPES = (
    "'dataset_source', 'run_metrics', 'failure_cases', 'summary_report', "
    "'human_review_packet', 'agent_execution'"
)


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_artifact_references_artifact_type"), "artifact_references", type_="check"
    )
    op.create_check_constraint(
        "artifact_type",
        "artifact_references",
        f"artifact_type IN ({OLD_TYPES}, 'product_experiment_report')",
    )
    op.add_column(
        "product_experiments", sa.Column("report_artifact_reference_id", sa.Uuid(), nullable=True)
    )
    op.add_column("product_experiments", sa.Column("report_sha256", sa.String(64), nullable=True))
    op.add_column(
        "product_experiments", sa.Column("report_snapshot_sha256", sa.String(64), nullable=True)
    )
    op.create_check_constraint(
        "report_publication_complete",
        "product_experiments",
        "(report_artifact_reference_id IS NULL AND report_sha256 IS NULL "
        "AND report_snapshot_sha256 IS NULL) OR "
        "(report_artifact_reference_id IS NOT NULL AND report_sha256 IS NOT NULL "
        "AND report_snapshot_sha256 IS NOT NULL)",
    )
    op.create_foreign_key(
        "fk_product_experiments_report_identity",
        "product_experiments",
        "artifact_references",
        ["report_artifact_reference_id", "tenant_id", "baseline_run_id", "report_sha256"],
        ["id", "tenant_id", "run_id", "blob_sha256"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    # Refuse a rollback with existing reports instead of deleting their evidence.
    # PostgreSQL transactional DDL restores the previous constraint if this check fails.
    op.drop_constraint(
        op.f("ck_artifact_references_artifact_type"), "artifact_references", type_="check"
    )
    op.create_check_constraint(
        "artifact_type", "artifact_references", f"artifact_type IN ({OLD_TYPES})"
    )
    op.drop_constraint(
        "fk_product_experiments_report_identity", "product_experiments", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("ck_product_experiments_report_publication_complete"),
        "product_experiments",
        type_="check",
    )
    op.drop_column("product_experiments", "report_snapshot_sha256")
    op.drop_column("product_experiments", "report_sha256")
    op.drop_column("product_experiments", "report_artifact_reference_id")
