"""Add direct tenant lineage and PostgreSQL RLS policies to core evaluation records."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260808_0015"
down_revision: str | None = "20260803_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES = ("datasets", "dataset_versions", "evaluation_runs", "case_results")


def _tenant_policy_sql(table: str) -> str:
    predicate = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    return f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
        USING ({predicate})
        WITH CHECK ({predicate})
    """


def upgrade() -> None:
    op.add_column("case_results", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE case_results
            SET tenant_id = evaluation_runs.tenant_id
            FROM evaluation_runs
            WHERE case_results.run_id = evaluation_runs.id
            """
        )
    )
    op.alter_column("case_results", "tenant_id", existing_type=sa.Uuid(), nullable=False)
    op.create_foreign_key(
        "fk_case_results_tenant_id_tenants",
        "case_results",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_case_results_run_id_tenant_id_evaluation_runs",
        "case_results",
        "evaluation_runs",
        ["run_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_case_results_tenant_id_run_id",
        "case_results",
        ["tenant_id", "run_id"],
    )

    for table in RLS_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(_tenant_policy_sql(table)))


def downgrade() -> None:
    for table in reversed(RLS_TABLES):
        op.execute(sa.text(f"DROP POLICY {table}_tenant_isolation ON {table}"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))

    op.drop_index("ix_case_results_tenant_id_run_id", table_name="case_results")
    op.drop_constraint(
        "fk_case_results_run_id_tenant_id_evaluation_runs",
        "case_results",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_case_results_tenant_id_tenants",
        "case_results",
        type_="foreignkey",
    )
    op.drop_column("case_results", "tenant_id")
