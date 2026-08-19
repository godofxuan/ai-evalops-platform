"""Add immutable, tenant-owned Agent execution artifact metadata."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260819_0019"
down_revision: str | None = "20260810_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_ARTIFACT_TYPE_CHECK = (
    "artifact_type IN ('dataset_source', 'run_metrics', 'failure_cases', "
    "'summary_report', 'human_review_packet')"
)
_NEW_ARTIFACT_TYPE_CHECK = (
    "artifact_type IN ('dataset_source', 'run_metrics', 'failure_cases', "
    "'summary_report', 'human_review_packet', 'agent_execution')"
)


def upgrade() -> None:
    op.drop_constraint("ck_artifact_references_artifact_type", "artifact_references", type_="check")
    op.create_check_constraint(
        "artifact_type",
        "artifact_references",
        _NEW_ARTIFACT_TYPE_CHECK,
    )
    op.create_table(
        "agent_execution_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.String(length=200), nullable=False),
        sa.Column("artifact_reference_id", sa.Uuid(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("framework", sa.String(length=100), nullable=False),
        sa.Column("session_id", sa.String(length=200), nullable=False),
        sa.Column("terminal_state", sa.String(length=100), nullable=True),
        sa.Column("usage_json", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("metadata_json", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "tenant_id"],
            ["evaluation_runs.id", "evaluation_runs.tenant_id"],
            name="fk_agent_exec_run_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "run_id"],
            ["evaluation_jobs.id", "evaluation_jobs.run_id"],
            name="fk_agent_exec_job_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_reference_id"],
            ["artifact_references.id"],
            name="fk_agent_exec_reference",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_execution_artifacts"),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "case_id",
            "content_sha256",
            name="uq_agent_execution_artifacts_content_identity",
        ),
    )
    op.create_index(
        "ix_agent_execution_artifacts_tenant_id_run_id_case_id",
        "agent_execution_artifacts",
        ["tenant_id", "run_id", "case_id"],
    )
    op.create_index(
        "ix_agent_execution_artifacts_job_id_created_at",
        "agent_execution_artifacts",
        ["job_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_execution_artifacts_job_id_created_at",
        table_name="agent_execution_artifacts",
    )
    op.drop_index(
        "ix_agent_execution_artifacts_tenant_id_run_id_case_id",
        table_name="agent_execution_artifacts",
    )
    op.drop_table("agent_execution_artifacts")
    op.drop_constraint("ck_artifact_references_artifact_type", "artifact_references", type_="check")
    op.create_check_constraint(
        "artifact_type",
        "artifact_references",
        _OLD_ARTIFACT_TYPE_CHECK,
    )
