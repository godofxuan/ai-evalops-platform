"""Pin immutable Agent regression evidence manifests."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260820_0021"
down_revision: str | None = "20260819_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_agent_eval_results_id_tenant_run",
        "agent_evaluation_results",
        ["id", "tenant_id", "run_id"],
    )
    op.create_table(
        "agent_regression_comparisons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("left_run_id", sa.Uuid(), nullable=False),
        sa.Column("right_run_id", sa.Uuid(), nullable=False),
        sa.Column("left_dataset_version_id", sa.Uuid(), nullable=True),
        sa.Column("right_dataset_version_id", sa.Uuid(), nullable=True),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("case_set_policy", sa.String(length=32), nullable=False),
        sa.Column("gate_config_json", postgresql.JSONB(), nullable=False),
        sa.Column("report_json", postgresql.JSONB(), nullable=False),
        sa.Column("decision_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["left_run_id", "tenant_id"],
            ["evaluation_runs.id", "evaluation_runs.tenant_id"],
            name="fk_agent_regression_left_run_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["right_run_id", "tenant_id"],
            ["evaluation_runs.id", "evaluation_runs.tenant_id"],
            name="fk_agent_regression_right_run_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_regression_comparisons"),
        sa.UniqueConstraint(
            "tenant_id",
            "request_sha256",
            name="uq_agent_regression_comparison_request",
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_agent_regression_comparison_id_tenant"),
    )
    op.create_index(
        "ix_agent_regression_comparisons_tenant_created",
        "agent_regression_comparisons",
        ["tenant_id", "created_at"],
    )
    op.create_table(
        "agent_regression_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("comparison_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("left_run_id", sa.Uuid(), nullable=False),
        sa.Column("right_run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.String(length=200), nullable=False),
        sa.Column("left_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("right_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("evaluator_kind", sa.String(length=64), nullable=False),
        sa.Column("left_evaluator_result_id", sa.Uuid(), nullable=True),
        sa.Column("right_evaluator_result_id", sa.Uuid(), nullable=True),
        sa.Column("left_implementation_version", sa.String(length=64), nullable=True),
        sa.Column("right_implementation_version", sa.String(length=64), nullable=True),
        sa.Column("left_config_sha256", sa.String(length=64), nullable=True),
        sa.Column("right_config_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["comparison_id", "tenant_id"],
            ["agent_regression_comparisons.id", "agent_regression_comparisons.tenant_id"],
            name="fk_agent_regression_evidence_comparison_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["left_artifact_id", "tenant_id", "left_run_id"],
            [
                "agent_execution_artifacts.id",
                "agent_execution_artifacts.tenant_id",
                "agent_execution_artifacts.run_id",
            ],
            name="fk_agent_regression_evidence_left_artifact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["right_artifact_id", "tenant_id", "right_run_id"],
            [
                "agent_execution_artifacts.id",
                "agent_execution_artifacts.tenant_id",
                "agent_execution_artifacts.run_id",
            ],
            name="fk_agent_regression_evidence_right_artifact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["left_evaluator_result_id", "tenant_id", "left_run_id"],
            [
                "agent_evaluation_results.id",
                "agent_evaluation_results.tenant_id",
                "agent_evaluation_results.run_id",
            ],
            name="fk_agent_regression_evidence_left_result",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["right_evaluator_result_id", "tenant_id", "right_run_id"],
            [
                "agent_evaluation_results.id",
                "agent_evaluation_results.tenant_id",
                "agent_evaluation_results.run_id",
            ],
            name="fk_agent_regression_evidence_right_result",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_regression_evidence"),
        sa.UniqueConstraint(
            "comparison_id",
            "case_id",
            "evaluator_kind",
            name="uq_agent_regression_evidence_case_kind",
        ),
    )
    op.create_index(
        "ix_agent_regression_evidence_tenant_comparison",
        "agent_regression_evidence",
        ["tenant_id", "comparison_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_regression_evidence_tenant_comparison",
        table_name="agent_regression_evidence",
    )
    op.drop_table("agent_regression_evidence")
    op.drop_index(
        "ix_agent_regression_comparisons_tenant_created",
        table_name="agent_regression_comparisons",
    )
    op.drop_table("agent_regression_comparisons")
    op.drop_constraint(
        "uq_agent_eval_results_id_tenant_run",
        "agent_evaluation_results",
        type_="unique",
    )
