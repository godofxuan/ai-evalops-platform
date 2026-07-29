from uuid import UUID

from sqlalchemy.dialects import postgresql

from app.domain.enums import JobStatus
from app.results.schemas import CaseQuery
from app.results.service import build_case_page_statement

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")


def test_metric_case_query_is_tenant_scoped_keyset_sql_without_offset() -> None:
    statement, _ = build_case_page_statement(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        query=CaseQuery(
            limit=20,
            status=JobStatus.FAILED,
            error_code="target_timeout",
            sort="metric",
            metric_name="lexical_f1",
            direction="desc",
        ),
        position=None,
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert f"evaluation_runs.tenant_id = '{TENANT_ID}'" in sql
    assert f"evaluation_jobs.run_id = '{RUN_ID}'" in sql
    assert "evaluation_jobs.status = 'failed'" in sql
    assert "evaluation_jobs.last_error_code = 'target_timeout'" in sql
    assert "jsonb_typeof" in sql
    assert "lexical_f1" in sql
    assert "NULLS LAST" in sql
    assert "LIMIT 21" in sql
    assert "OFFSET" not in sql
