from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.dialects import postgresql

from app.jobs.claiming import (
    build_pending_scheduler_permit_statement,
    build_scheduler_round_members_statement,
    build_tenant_job_claim_statement,
)

NOW = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)
TENANT_ID = UUID("00000000-0000-0000-0000-000000000301")


def compile_postgresql(statement: object) -> str:
    return str(
        statement.compile(  # type: ignore[union-attr]
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_round_members_include_each_tenant_only_at_highest_eligible_priority() -> None:
    sql = compile_postgresql(build_scheduler_round_members_statement(now=NOW))

    assert "max(evaluation_jobs.priority)" in sql
    assert "GROUP BY evaluation_runs.tenant_id" in sql
    assert "row_number() OVER" in sql
    assert "evaluation_jobs.priority =" in sql
    assert "evaluation_runs.status IN ('queued', 'running')" in sql


def test_fast_permit_selector_locks_only_current_pending_tenant_state() -> None:
    sql = compile_postgresql(build_pending_scheduler_permit_statement(skip_locked=True))

    assert "JOIN scheduler_coordination" in sql
    assert "tenant_scheduler_states.generation = scheduler_coordination.active_generation" in sql
    assert "tenant_scheduler_states.status = 'pending'" in sql
    assert "ORDER BY tenant_scheduler_states.permit_order ASC" in sql
    assert "FOR UPDATE OF tenant_scheduler_states SKIP LOCKED" in sql


def test_waiting_permit_selector_uses_same_order_without_skip_locked() -> None:
    sql = compile_postgresql(build_pending_scheduler_permit_statement(skip_locked=False))

    assert "FOR UPDATE OF tenant_scheduler_states" in sql
    assert "SKIP LOCKED" not in sql


def test_round_job_claim_is_scoped_to_frozen_tenant_priority() -> None:
    sql = compile_postgresql(
        build_tenant_job_claim_statement(
            now=NOW,
            tenant_id=TENANT_ID,
            priority=7,
        )
    )

    assert "evaluation_runs.tenant_id" in sql
    assert "evaluation_jobs.priority = 7" in sql
    assert "FOR UPDATE OF evaluation_jobs SKIP LOCKED" in sql
