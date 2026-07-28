from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql

from app.jobs.claiming import (
    InvalidClaimRequest,
    build_claim_candidates_statement,
    validate_claim_request,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def compile_postgresql(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_claim_candidates_use_postgresql_skip_locked_and_deterministic_order() -> None:
    sql = compile_postgresql(build_claim_candidates_statement(now=NOW, limit=10))

    assert "FOR UPDATE OF evaluation_jobs SKIP LOCKED" in sql
    assert "evaluation_jobs.status" in sql
    assert "evaluation_jobs.next_attempt_at" in sql
    assert "evaluation_runs.status" in sql
    assert (
        "ORDER BY evaluation_jobs.priority DESC, evaluation_jobs.created_at ASC, "
        "evaluation_jobs.id ASC" in sql
    )
    assert "LIMIT 10" in sql


@pytest.mark.parametrize(("worker_id", "limit"), [("", 1), ("worker-1", 0), ("worker-1", 101)])
def test_claim_request_rejects_unsafe_worker_or_batch_values(
    worker_id: str,
    limit: int,
) -> None:
    with pytest.raises(InvalidClaimRequest):
        validate_claim_request(worker_id=worker_id, limit=limit)
