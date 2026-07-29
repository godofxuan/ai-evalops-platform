"""Add Run metrics and Run-owned artifact metadata.

Revision ID: 20260729_0006
Revises: 20260729_0005
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260729_0006"
down_revision: str | None = "20260729_0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_artifacts_artifact_type"), "artifacts", type_="check")
    op.create_check_constraint(
        "artifact_type",
        "artifacts",
        "artifact_type IN ('dataset_source', 'run_metrics', 'failure_cases', 'summary_report')",
    )
    op.add_column("artifacts", sa.Column("run_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_artifacts_run_id_evaluation_runs",
        "artifacts",
        "evaluation_runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_artifacts_run_id_artifact_type",
        "artifacts",
        ["run_id", "artifact_type"],
        unique=False,
    )
    op.create_table(
        "run_metrics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("metric_name", sa.String(length=200), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=True),
        sa.Column(
            "metric_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["evaluation_runs.id"],
            name="fk_run_metrics_run_id_evaluation_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_run_metrics"),
        sa.UniqueConstraint(
            "run_id",
            "metric_name",
            name="uq_run_metrics_run_id_metric_name",
        ),
    )
    op.create_index(
        "ix_run_metrics_run_id_created_at",
        "run_metrics",
        ["run_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_run_metrics_run_id_created_at", table_name="run_metrics")
    op.drop_table("run_metrics")
    op.drop_index("ix_artifacts_run_id_artifact_type", table_name="artifacts")
    op.drop_constraint(
        "fk_artifacts_run_id_evaluation_runs",
        "artifacts",
        type_="foreignkey",
    )
    op.drop_column("artifacts", "run_id")
    op.drop_constraint(op.f("ck_artifacts_artifact_type"), "artifacts", type_="check")
    op.create_check_constraint(
        "artifact_type",
        "artifacts",
        "artifact_type IN ('dataset_source')",
    )
