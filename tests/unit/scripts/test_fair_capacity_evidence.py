import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql

from scripts.fair_capacity_evidence import (
    FAULT_EVIDENCE_SOURCE_COMMIT,
    assess_arm_runtime,
    build_fair_capacity_plan,
    build_legacy_fifo_statement,
    order_timed_values,
    queue_sizes_for_stage,
    summarize_explain,
    tenant_job_counts,
    validate_stage_request,
    write_release_manifest,
)
from scripts.release_evidence import assess_release_bundle


def test_fault_evidence_reference_is_the_audited_after_bundle_source() -> None:
    assert FAULT_EVIDENCE_SOURCE_COMMIT == "03d6987c75f2169c8207f2355f1f9d7528f9d223"


def test_order_timed_values_uses_global_event_time_not_worker_list_order() -> None:
    events = ((3.0, "worker-a-second"), (1.0, "worker-b-first"), (2.0, "worker-a-first"))

    assert order_timed_values(events) == (
        "worker-b-first",
        "worker-a-first",
        "worker-a-second",
    )


def _valid_skew_runtime() -> dict[str, object]:
    return {
        "distribution": "skew_20_to_1",
        "sample_jobs": 100,
        "claimed_jobs": 100,
        "tenant_first_claim_positions": {"tenant-a": 1, "tenant-b": 2},
        "stale_success_accepted_count": 0,
        "stale_failure_accepted_count": 0,
        "illegal_state_transition_count": 0,
        "correctness": {
            "submitted_count": 100,
            "unique_job_count": 100,
            "terminal_count": 100,
            "lost_count": 0,
            "duplicate_durable_result_count": 0,
            "orphan_nonterminal_count": 0,
            "attempt_sequence_mismatch_count": 0,
        },
    }


def test_assess_arm_runtime_accepts_complete_fair_skew_sample() -> None:
    assessment = assess_arm_runtime(
        _valid_skew_runtime(),
        expected_tenant_ids=("tenant-a", "tenant-b"),
    )

    assert assessment == {"status": "VERIFIED", "failures": []}


@pytest.mark.parametrize(
    ("mutation", "expected_failure"),
    [
        (
            lambda runtime: runtime["tenant_first_claim_positions"].update(  # type: ignore[union-attr]
                {"tenant-b": 3}
            ),
            "skew_secondary_tenant_first_claim_position_exceeds_2",
        ),
        (
            lambda runtime: runtime["correctness"].update(  # type: ignore[union-attr]
                {"attempt_sequence_mismatch_count": 1}
            ),
            "attempt_sequence_mismatch_count_nonzero",
        ),
    ],
)
def test_assess_arm_runtime_rejects_fairness_or_attempt_regression(
    mutation: object,
    expected_failure: str,
) -> None:
    runtime = _valid_skew_runtime()
    assert callable(mutation)
    mutation(runtime)

    assessment = assess_arm_runtime(
        runtime,
        expected_tenant_ids=("tenant-a", "tenant-b"),
    )

    assert assessment["status"] == "FAILED"
    assert expected_failure in assessment["failures"]


def test_fair_capacity_plan_covers_1k_10k_distributions_and_worker_counts() -> None:
    arms = build_fair_capacity_plan(queue_sizes=(1_000, 10_000))

    assert len(arms) == 32
    assert len({arm.arm_id for arm in arms}) == 32
    assert {arm.queue_size for arm in arms} == {1_000, 10_000}
    assert {arm.distribution for arm in arms} == {
        "single_tenant",
        "balanced_multi_tenant",
        "skew_20_to_1",
        "many_small_tenants",
    }
    assert {arm.worker_concurrency for arm in arms} == {1, 2, 4, 8}
    assert {arm.claim_batch_size for arm in arms} == {1}


@pytest.mark.parametrize("queue_size", [1_000, 10_000, 100_000])
def test_tenant_job_counts_materialize_each_distribution(queue_size: int) -> None:
    single = tenant_job_counts(queue_size=queue_size, distribution="single_tenant")
    balanced = tenant_job_counts(queue_size=queue_size, distribution="balanced_multi_tenant")
    skewed = tenant_job_counts(queue_size=queue_size, distribution="skew_20_to_1")
    many = tenant_job_counts(queue_size=queue_size, distribution="many_small_tenants")

    assert len(single) == 1
    assert len(balanced) == 4
    assert max(balanced) - min(balanced) <= 1
    assert len(skewed) == 2
    assert 19 * skewed[1] <= skewed[0] <= 21 * skewed[1]
    assert len(many) == 100
    assert max(many) - min(many) <= 1
    assert {sum(values) for values in (single, balanced, skewed, many)} == {queue_size}


def test_legacy_fifo_selector_is_benchmark_only_global_order() -> None:
    statement = build_legacy_fifo_statement(
        now=datetime(2026, 8, 8, tzinfo=UTC),
        limit=1,
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "row_number()" not in sql
    assert "JOIN tenants" not in sql
    assert "evaluation_jobs.priority DESC" in sql
    assert "evaluation_jobs.created_at ASC" in sql
    assert "FOR UPDATE OF evaluation_jobs SKIP LOCKED" in sql


def test_explain_summary_preserves_buffers_sort_spill_and_candidate_cardinality() -> None:
    raw_plan = [
        {
            "Planning Time": 1.25,
            "Execution Time": 8.5,
            "Plan": {
                "Node Type": "Limit",
                "Actual Rows": 1,
                "Actual Loops": 1,
                "Shared Hit Blocks": 20,
                "Shared Read Blocks": 3,
                "Temp Read Blocks": 4,
                "Temp Written Blocks": 5,
                "Plans": [
                    {
                        "Node Type": "Sort",
                        "Actual Rows": 1_000,
                        "Actual Loops": 1,
                        "Sort Method": "external merge",
                        "Sort Space Used": 256,
                        "Sort Space Type": "Disk",
                        "Plans": [
                            {
                                "Node Type": "WindowAgg",
                                "Actual Rows": 10_000,
                                "Actual Loops": 1,
                            }
                        ],
                    }
                ],
            },
        }
    ]

    summary = summarize_explain(raw_plan)

    assert summary == {
        "planning_time_ms": 1.25,
        "execution_time_ms": 8.5,
        "rows": 1,
        "loops": 1,
        "shared_hit_blocks": 20,
        "shared_read_blocks": 3,
        "temp_read_blocks": 4,
        "temp_written_blocks": 5,
        "candidate_cardinality": 10_000,
        "sorts": [
            {
                "method": "external merge",
                "space_used_kb": 256,
                "space_type": "Disk",
            }
        ],
        "temp_spill": True,
    }
    assert "cpu_time_ms" not in summary


def test_100k_stage_requires_verified_1k_10k_correctness() -> None:
    assert queue_sizes_for_stage(stage="initial", prior_status=None) == (1_000, 10_000)
    assert queue_sizes_for_stage(stage="large", prior_status="VERIFIED") == (100_000,)

    with pytest.raises(ValueError, match="VERIFIED"):
        queue_sizes_for_stage(stage="large", prior_status="FAILED")


def test_large_stage_binds_verified_prior_assessment_to_same_source() -> None:
    source = "a" * 40
    assert validate_stage_request(
        stage="large",
        requested_queue_sizes=(100_000,),
        source_commit=source,
        prior_assessment={"status": "VERIFIED", "source_commit": source},
    ) == (100_000,)

    with pytest.raises(ValueError, match="source"):
        validate_stage_request(
            stage="large",
            requested_queue_sizes=(100_000,),
            source_commit=source,
            prior_assessment={"status": "VERIFIED", "source_commit": "b" * 40},
        )


def test_stage_rejects_queue_sizes_outside_frozen_plan() -> None:
    with pytest.raises(ValueError, match="queue sizes"):
        validate_stage_request(
            stage="initial",
            requested_queue_sizes=(1_000,),
            source_commit="a" * 40,
            prior_assessment=None,
        )


def test_release_manifest_binds_payload_set_and_source(tmp_path: Path) -> None:
    row = {
        "arm_id": "fair-q1000-single-w1-b1",
        "source_commit": "a" * 40,
        "distribution": "single_tenant",
        "fair_first_secondary_tenant_position": "",
        "legacy_fifo_first_secondary_tenant_position": "",
        "submitted_count": 500,
        "unique_job_count": 500,
        "terminal_count": 500,
        "lost_count": 0,
        "duplicate_durable_result_count": 0,
        "stale_success_accepted_count": 0,
        "stale_failure_accepted_count": 0,
        "illegal_state_transition_count": 0,
        "orphan_nonterminal_count": 0,
        "attempt_sequence_mismatch_count": 0,
    }
    with (tmp_path / "arms.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row), lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)
    explain = tmp_path / "explain" / "fair.json"
    explain.parent.mkdir()
    explain.write_text(
        json.dumps(
            {
                "format": "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)",
                "planning_time_ms": 1.0,
                "execution_time_ms": 2.0,
                "plan": [{"Plan": {"Node Type": "Limit"}}],
            }
        ),
        encoding="utf-8",
    )

    write_release_manifest(tmp_path, source_commit="a" * 40)
    result = assess_release_bundle(
        tmp_path,
        expected_source_commit="a" * 40,
        expected_arm_ids=("fair-q1000-single-w1-b1",),
    )

    assert result["status"] == "VERIFIED"
    assert set(json.loads((tmp_path / "manifest.json").read_text())["files"]) == {
        "arms.csv",
        "explain/fair.json",
    }
