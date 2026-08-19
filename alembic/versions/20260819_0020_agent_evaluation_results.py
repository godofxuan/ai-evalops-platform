"""Persist reproducible evaluator results for immutable Agent artifacts."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260819_0020"
down_revision: str | None = "20260819_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_agent_execution_artifacts_id_tenant_run",
        "agent_execution_artifacts",
        ["id", "tenant_id", "run_id"],
    )
    op.create_table(
        "agent_evaluation_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("evaluator_kind", sa.String(length=64), nullable=False),
        sa.Column("evaluator_version", sa.String(length=64), nullable=False),
        sa.Column("config_sha256", sa.String(length=64), nullable=False),
        sa.Column("config_json", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("metrics_json", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("failure_taxonomy_json", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id", "tenant_id", "run_id"],
            [
                "agent_execution_artifacts.id",
                "agent_execution_artifacts.tenant_id",
                "agent_execution_artifacts.run_id",
            ],
            name="fk_agent_eval_result_artifact_tenant_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_evaluation_results"),
        sa.UniqueConstraint(
            "artifact_id",
            "evaluator_kind",
            "evaluator_version",
            "config_sha256",
            name="uq_agent_eval_results_identity",
        ),
    )
    op.create_index(
        "ix_agent_evaluation_results_tenant_run_kind",
        "agent_evaluation_results",
        ["tenant_id", "run_id", "evaluator_kind"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_evaluation_results_tenant_run_kind",
        table_name="agent_evaluation_results",
    )
    op.drop_table("agent_evaluation_results")
    op.drop_constraint(
        "uq_agent_execution_artifacts_id_tenant_run",
        "agent_execution_artifacts",
        type_="unique",
    )
