from uuid import UUID

from sqlalchemy.dialects import postgresql

from app.runs.repository import (
    build_find_run_by_idempotency_statement,
    build_get_dataset_version_source_statement,
    build_get_run_statement,
)

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
DATASET_VERSION_ID = UUID("00000000-0000-0000-0000-000000000401")


def compile_postgresql(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_run_lookup_statements_always_include_tenant_boundary() -> None:
    idempotency_sql = compile_postgresql(
        build_find_run_by_idempotency_statement(TENANT_ID, "create-rag-v1")
    )
    run_sql = compile_postgresql(build_get_run_statement(TENANT_ID, RUN_ID))

    assert "evaluation_runs.tenant_id" in idempotency_sql
    assert "evaluation_runs.id" in run_sql
    assert "evaluation_runs.tenant_id" in run_sql


def test_dataset_version_source_query_reaches_artifact_through_tenant_dataset() -> None:
    sql = compile_postgresql(
        build_get_dataset_version_source_statement(TENANT_ID, DATASET_VERSION_ID)
    )

    assert "JOIN datasets" in sql
    assert "JOIN artifacts" in sql
    assert "datasets.tenant_id" in sql
    assert "artifacts.tenant_id" in sql
