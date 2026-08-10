import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql

from scripts import run_fair_capacity_test
from scripts.experiment_support import ExperimentError
from scripts.fair_capacity_evidence import (
    FAULT_EVIDENCE_SOURCE_COMMIT,
    assess_arm_runtime,
    build_failure_report,
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
from scripts.run_fair_capacity_test import ClaimPhaseRecorder


def test_fault_evidence_reference_is_the_audited_after_bundle_source() -> None:
    assert FAULT_EVIDENCE_SOURCE_COMMIT == "03d6987c75f2169c8207f2355f1f9d7528f9d223"


class ManualNanosecondClock:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> int:
        return self.value

    def advance_ms(self, value: float) -> None:
        self.value += int(value * 1_000_000)


class CountingNanosecondClock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> int:
        self.calls += 1
        return 0


def test_claim_phase_recorder_derives_registered_stage_timings() -> None:
    clock = ManualNanosecondClock()
    recorder = ClaimPhaseRecorder(clock_ns=clock)

    recorder.observe("claim_entry")
    clock.advance_ms(1)
    recorder.observe("scheduler_coordination_start")
    clock.advance_ms(3)
    recorder.observe("scheduler_coordination_acquired")
    clock.advance_ms(1)
    recorder.observe("tenant_permit_select_start")
    clock.advance_ms(4)
    recorder.observe("tenant_permit_acquired")
    clock.advance_ms(1)
    recorder.observe("job_row_select_start")
    clock.advance_ms(6)
    recorder.observe("job_row_acquired")
    clock.advance_ms(4)
    recorder.observe("job_attempt_mutation_complete")
    clock.advance_ms(1)
    recorder.observe("durable_sequence_start")
    clock.advance_ms(5)
    recorder.observe("durable_sequence_updated")
    clock.advance_ms(1)
    recorder.observe("transaction_work_complete")
    clock.advance_ms(3)
    recorder.observe("transaction_complete")
    clock.advance_ms(5)
    recorder.observe("claim_return")

    summary = recorder.summary()

    assert summary["scheduler_coordination_wait_ms"]["observations"] == [3.0]
    assert summary["tenant_permit_wait_ms"]["observations"] == [4.0]
    assert summary["job_row_wait_ms"]["observations"] == [6.0]
    assert summary["job_row_wait_ms"]["count"] == 1
    assert summary["job_row_wait_ms"]["sum"] == 6.0
    assert summary["durable_sequence_wait_ms"]["observations"] == [5.0]
    assert summary["transaction_commit_ms"]["observations"] == [3.0]
    assert summary["claim_total_ms"]["observations"] == [35.0]
    assert summary["job_row_wait_ms"]["p50"] == 6.0
    assert summary["job_row_wait_ms"]["p95"] == 6.0
    assert summary["job_row_wait_ms"]["p99"] == 6.0


def test_claim_phase_recorder_counts_scheduler_events_without_entity_ids() -> None:
    recorder = ClaimPhaseRecorder(clock_ns=lambda: 0)

    for phase in (
        "round_created",
        "generation_advanced",
        "tenant_permit_acquired",
        "permit_retained",
        "job_skip_locked_miss",
        "tenant_permit_consumed",
        "tenant_permit_empty",
    ):
        recorder.observe(phase)

    assert recorder.counters() == {
        "generation_advance_count": 1,
        "job_skip_locked_miss_count": 1,
        "permit_consumed_count": 1,
        "permit_empty_count": 1,
        "permit_pending_count": 2,
        "round_created_count": 1,
    }
    assert all("tenant" not in key and "job_id" not in key for key in recorder.counters())


def test_claim_phase_recorder_does_not_read_clock_for_counter_only_or_ignored_events() -> None:
    clock = CountingNanosecondClock()
    recorder = ClaimPhaseRecorder(clock_ns=clock)

    for phase in (
        "transaction_start",
        "tenant_permit_missing",
        "job_attempt_mutation_complete",
        "round_created",
        "generation_advanced",
        "permit_retained",
        "job_skip_locked_miss",
        "tenant_permit_consumed",
        "tenant_permit_empty",
    ):
        recorder.observe(phase)

    assert clock.calls == 0
    assert recorder.counters() == {
        "generation_advance_count": 1,
        "job_skip_locked_miss_count": 1,
        "permit_consumed_count": 1,
        "permit_empty_count": 1,
        "permit_pending_count": 1,
        "round_created_count": 1,
    }


def test_benchmark_cli_selects_one_exact_existing_arm() -> None:
    arm_id = "fair-q1000-skew_20_to_1-w8-b1"
    args = run_fair_capacity_test.build_parser().parse_args(
        [
            "--run-id",
            "overhead-off-rep1",
            "--source-commit",
            "a" * 40,
            "--stage",
            "targeted",
            "--queue-sizes",
            "1000",
            "--arm-id",
            arm_id,
        ]
    )

    selected = run_fair_capacity_test.select_requested_arms(
        build_fair_capacity_plan(queue_sizes=(1000,)),
        arm_id=args.arm_id,
    )

    assert [arm.arm_id for arm in selected] == [arm_id]


def test_benchmark_arm_selector_rejects_unknown_arm() -> None:
    with pytest.raises(ExperimentError, match="requested benchmark arm is not in frozen plan"):
        run_fair_capacity_test.select_requested_arms(
            build_fair_capacity_plan(queue_sizes=(1000,)),
            arm_id="fair-q1000-skew_20_to_1-w16-b1",
        )


def test_failure_report_preserves_task_group_leaf_exception_and_cause() -> None:
    try:
        try:
            raise TimeoutError("claim exceeded the diagnostic boundary")
        except TimeoutError as cause:
            raise RuntimeError("worker sample failed") from cause
    except RuntimeError as worker_error:
        error = ExceptionGroup("worker tasks failed", [worker_error])

    report = build_failure_report(
        error,
        recorded_at=datetime(2026, 8, 8, tzinfo=UTC),
    )

    assert report["status"] == "FAILED"
    assert report["error_type"] == "ExceptionGroup"
    assert report["error_message"] == "worker tasks failed (1 sub-exception)"
    assert report["recorded_at"] == "2026-08-08T00:00:00+00:00"
    assert report["exception"]["children"][0]["error_type"] == "RuntimeError"
    assert report["exception"]["children"][0]["cause"] == {
        "error_type": "TimeoutError",
        "error_message": "claim exceeded the diagnostic boundary",
    }
    assert "RuntimeError: worker sample failed" in report["traceback"]
    assert "TimeoutError: claim exceeded the diagnostic boundary" in report["traceback"]


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
                "Actual Rows": 1.0,
                "Actual Loops": 1,
                "Shared Hit Blocks": 20,
                "Shared Read Blocks": 3,
                "Temp Read Blocks": 4,
                "Temp Written Blocks": 5,
                "Plans": [
                    {
                        "Node Type": "Sort",
                        "Actual Rows": 1_000.0,
                        "Actual Loops": 1,
                        "Sort Method": "external merge",
                        "Sort Space Used": 256,
                        "Sort Space Type": "Disk",
                        "Plans": [
                            {
                                "Node Type": "WindowAgg",
                                "Actual Rows": 10_000.0,
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


def test_explain_summary_uses_largest_plan_row_count_without_window_aggregate() -> None:
    raw_plan = [
        {
            "Planning Time": 0.5,
            "Execution Time": 2.5,
            "Plan": {
                "Node Type": "Limit",
                "Actual Rows": 1.0,
                "Actual Loops": 1,
                "Plans": [
                    {
                        "Node Type": "Seq Scan",
                        "Actual Rows": 1_000.0,
                        "Actual Loops": 1,
                    }
                ],
            },
        }
    ]

    summary = summarize_explain(raw_plan)

    assert summary["candidate_cardinality"] == 1_000


def test_explain_summary_ignores_invisible_bitmap_index_entries() -> None:
    raw_plan = [
        {
            "Planning Time": 0.5,
            "Execution Time": 2.5,
            "Plan": {
                "Node Type": "Limit",
                "Actual Rows": 1.0,
                "Actual Loops": 1,
                "Plans": [
                    {
                        "Node Type": "Bitmap Heap Scan",
                        "Relation Name": "evaluation_jobs",
                        "Actual Rows": 1_000.0,
                        "Actual Loops": 1,
                        "Plans": [
                            {
                                "Node Type": "Bitmap Index Scan",
                                "Actual Rows": 4_000.0,
                                "Actual Loops": 1,
                            }
                        ],
                    }
                ],
            },
        }
    ]

    summary = summarize_explain(raw_plan)

    assert summary["candidate_cardinality"] == 1_000


def test_explain_summary_uses_visible_job_rows_when_window_has_a_run_condition() -> None:
    raw_plan = [
        {
            "Planning Time": 0.5,
            "Execution Time": 2.5,
            "Plan": {
                "Node Type": "Limit",
                "Actual Rows": 1.0,
                "Actual Loops": 1,
                "Plans": [
                    {
                        "Node Type": "WindowAgg",
                        "Actual Rows": 1.0,
                        "Actual Loops": 1_000,
                        "Run Condition": "row_number() OVER w1 <= 1",
                        "Plans": [
                            {
                                "Node Type": "Bitmap Heap Scan",
                                "Relation Name": "evaluation_jobs",
                                "Actual Rows": 1_000.0,
                                "Actual Loops": 1,
                                "Plans": [
                                    {
                                        "Node Type": "Bitmap Index Scan",
                                        "Actual Rows": 4_000.0,
                                        "Actual Loops": 1,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        }
    ]

    summary = summarize_explain(raw_plan)

    assert summary["candidate_cardinality"] == 1_000


def test_explain_summary_counts_visible_job_rows_across_relation_loops() -> None:
    raw_plan = [
        {
            "Planning Time": 0.5,
            "Execution Time": 2.5,
            "Plan": {
                "Node Type": "Bitmap Heap Scan",
                "Relation Name": "evaluation_jobs",
                "Actual Rows": 10.0,
                "Actual Loops": 100,
            },
        }
    ]

    summary = summarize_explain(raw_plan)

    assert summary["candidate_cardinality"] == 1_000


def test_explain_summary_does_not_multiply_repeated_full_table_scans() -> None:
    raw_plan = [
        {
            "Planning Time": 0.5,
            "Execution Time": 2.5,
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "evaluation_jobs",
                "Actual Rows": 10_000.0,
                "Actual Loops": 4,
            },
        }
    ]

    summary = summarize_explain(raw_plan)

    assert summary["candidate_cardinality"] == 10_000


def test_100k_stage_requires_verified_1k_10k_correctness() -> None:
    assert queue_sizes_for_stage(stage="targeted", prior_status=None) == (1_000,)
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


def test_targeted_stage_is_an_independent_one_thousand_job_gate() -> None:
    assert validate_stage_request(
        stage="targeted",
        requested_queue_sizes=(1_000,),
        source_commit="a" * 40,
        prior_assessment=None,
    ) == (1_000,)

    with pytest.raises(ValueError, match="must not consume"):
        validate_stage_request(
            stage="targeted",
            requested_queue_sizes=(1_000,),
            source_commit="a" * 40,
            prior_assessment={"status": "VERIFIED", "source_commit": "a" * 40},
        )


def test_release_manifest_binds_payload_set_and_source(tmp_path: Path) -> None:
    row = {
        "arm_id": "fair-q1000-single-w1-b1",
        "source_commit": "a" * 40,
        "queue_size": 1_000,
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
                "arm_id": "fair-q1000-single-w1-b1",
                "candidate_cardinality": 1_000,
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


def test_release_manifest_can_emit_current_schema_version(tmp_path: Path) -> None:
    (tmp_path / "payload.json").write_text("{}\n", encoding="utf-8")

    write_release_manifest(tmp_path, source_commit="a" * 40, schema_version=2)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2


def test_release_manifest_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    (tmp_path / "payload.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="supported schema version"):
        write_release_manifest(tmp_path, source_commit="a" * 40, schema_version=3)


def test_release_manifest_rejects_boolean_schema_version(tmp_path: Path) -> None:
    (tmp_path / "payload.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="supported schema version"):
        write_release_manifest(tmp_path, source_commit="a" * 40, schema_version=True)
