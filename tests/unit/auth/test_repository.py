from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.dialects import postgresql

from app.auth.repository import build_find_candidate_statement, build_mark_used_statement


def compiled_sql(statement: object) -> str:
    compiled = statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    return " ".join(str(compiled).lower().split())


def test_find_candidate_statement_joins_tenant_and_filters_safe_prefix() -> None:
    sql = compiled_sql(build_find_candidate_statement("evk_001122334455"))

    assert "from api_keys join tenants on tenants.id = api_keys.tenant_id" in sql
    assert "where api_keys.key_prefix = 'evk_001122334455'" in sql


def test_mark_used_statement_rechecks_key_tenant_and_expiration_state() -> None:
    sql = compiled_sql(
        build_mark_used_statement(
            UUID("00000000-0000-0000-0000-000000000101"),
            used_at=datetime(2026, 7, 29, 9, 0, tzinfo=UTC),
        )
    )

    assert "api_keys.status = 'active'" in sql
    assert "api_keys.expires_at is null or api_keys.expires_at >" in sql
    assert "exists (select 1" in sql
    assert "tenants.status = 'active'" in sql
    assert "returning api_keys.id" in sql
