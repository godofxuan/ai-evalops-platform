"""Add Agent evidence RLS policies and composite artifact-reference binding."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260820_0023"
down_revision: str | None = "20260820_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES = (
    "agent_execution_artifacts",
    "agent_evaluation_results",
    "agent_regression_comparisons",
    "agent_regression_evidence",
    "human_review_tasks",
    "human_review_submissions",
    "human_review_adjudications",
)


def _policy_sql(table: str) -> str:
    predicate = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    return f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
        USING ({predicate})
        WITH CHECK ({predicate})
    """


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_artifact_references_agent_binding",
        "artifact_references",
        ["id", "tenant_id", "run_id", "blob_sha256"],
    )
    op.drop_constraint("fk_agent_exec_reference", "agent_execution_artifacts", type_="foreignkey")
    op.create_foreign_key(
        "fk_agent_exec_reference_binding",
        "agent_execution_artifacts",
        "artifact_references",
        ["artifact_reference_id", "tenant_id", "run_id", "content_sha256"],
        ["id", "tenant_id", "run_id", "blob_sha256"],
        ondelete="RESTRICT",
    )
    for table in RLS_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(_policy_sql(table)))


def downgrade() -> None:
    for table in reversed(RLS_TABLES):
        op.execute(sa.text(f"DROP POLICY {table}_tenant_isolation ON {table}"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
    op.drop_constraint(
        "fk_agent_exec_reference_binding", "agent_execution_artifacts", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_agent_exec_reference",
        "agent_execution_artifacts",
        "artifact_references",
        ["artifact_reference_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_artifact_references_agent_binding", "artifact_references", type_="unique"
    )
