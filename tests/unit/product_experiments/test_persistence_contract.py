from dataclasses import replace
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
    with pytest.raises(ValueError, match="tenant"):
        replace(pair, candidate=replace(candidate, tenant_id=uuid4()))
    with pytest.raises(ValueError, match="dataset"):
        replace(pair, candidate=replace(candidate, dataset_version_id=uuid4()))
