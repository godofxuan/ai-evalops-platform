import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest

from app.runs.repository import NewRun


def test_paired_experiment_rejects_cross_tenant_or_mismatched_dataset_before_writes() -> None:
    from app.product_experiments.persistence import NewProductExperiment

    tenant, actor, dataset = uuid4(), uuid4(), uuid4()
    baseline = NewRun(
        tenant_id=tenant,
        created_by=actor,
        dataset_version_id=dataset,
        dataset_hash="a" * 64,
        idempotency_key="baseline",
        request_hash="b" * 64,
        target_type="mock",
        target_config={},
        target_config_hash="c" * 64,
        evaluator_type="product_qa_v2",
        evaluator_config={},
        evaluator_config_hash="d" * 64,
        target_version="v1",
        evaluator_version="product-v2",
        source_commit="e" * 40,
        max_attempts=1,
        cases=({"case_id": "q1"}, {"case_id": "q2"}),
    )
    candidate = replace(baseline, idempotency_key="candidate", target_version="v2")
    pair = NewProductExperiment(
        tenant_id=tenant,
        created_by=actor,
        idempotency_key="experiment",
        request_hash="f" * 64,
        snapshot={"schema_version": "test-only"},
        baseline=baseline,
        candidate=candidate,
    )
    assert pair.baseline.dataset_version_id == pair.candidate.dataset_version_id
    with pytest.raises(ValueError, match="attempt budget"):
        replace(pair, max_total_attempts=3)
    with pytest.raises(ValueError, match="tenant"):
        replace(pair, candidate=replace(candidate, tenant_id=uuid4()))
    with pytest.raises(ValueError, match="dataset"):
        replace(pair, candidate=replace(candidate, dataset_version_id=uuid4()))
    with pytest.raises(ValueError, match="actor"):
        replace(pair, candidate=replace(candidate, created_by=uuid4()))
    with pytest.raises(ValueError, match="cases"):
        replace(pair, candidate=replace(candidate, cases=({"case_id": "different"},)))
    with pytest.raises(ValueError, match="evaluator"):
        replace(pair, candidate=replace(candidate, evaluator_version="different"))
    with pytest.raises(ValueError, match="evaluator"):
        replace(pair, candidate=replace(candidate, evaluator_config={"override": True}))
    with pytest.raises(ValueError, match="deadline"):
        replace(
            pair,
            candidate=replace(candidate, execution_deadline_at=datetime(2030, 1, 1, tzinfo=UTC)),
        )
    # Frozen dataclasses still contain mutable case dictionaries. Revalidate before I/O.
    from app.product_experiments.persistence import SQLAlchemyProductExperimentRepository

    mutable_cases = tuple(dict(case) for case in candidate.cases)
    pending = replace(pair, candidate=replace(candidate, cases=mutable_cases))
    mutable_cases[0]["case_id"] = "changed-after-validation"
    repository = SQLAlchemyProductExperimentRepository(cast(Any, None))
    with pytest.raises(ValueError, match="cases"):
        asyncio.run(repository.create_or_replay(pending))
