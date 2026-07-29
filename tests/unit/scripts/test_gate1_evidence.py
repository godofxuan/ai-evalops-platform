from scripts.gate1_evidence import (
    aggregate_arm_summaries,
    reconcile_arm,
    summarize_arm,
)


def test_reconciliation_rejects_duplicate_durable_results() -> None:
    reconciliation = reconcile_arm(
        expected_jobs=2,
        run_snapshot={
            "id": "run-1",
            "status": "succeeded",
            "total_jobs": 2,
            "succeeded_jobs": 2,
            "failed_jobs": 0,
            "cancelled_jobs": 0,
        },
        jobs=[
            {
                "id": "job-1",
                "run_id": "run-1",
                "case_id": "load-0000",
                "status": "succeeded",
                "attempt_count": 1,
            },
            {
                "id": "job-2",
                "run_id": "run-1",
                "case_id": "load-0001",
                "status": "succeeded",
                "attempt_count": 1,
            },
        ],
        attempts=[
            {"job_id": "job-1", "attempt_number": 1},
            {"job_id": "job-2", "attempt_number": 1},
        ],
        case_results=[
            {
                "job_id": "job-1",
                "run_id": "run-1",
                "case_id": "load-0000",
            },
            {
                "job_id": "job-1",
                "run_id": "run-1",
                "case_id": "load-0000",
            },
        ],
    )

    assert reconciliation["valid_for_capacity_comparison"] is False
    assert reconciliation["duplicate_result_job_ids"] == ["job-1"]
    assert reconciliation["duplicate_result_run_case_keys"] == [
        {"run_id": "run-1", "case_id": "load-0000"}
    ]
    assert {violation["code"] for violation in reconciliation["violations"]} == {
        "duplicate_case_results_by_job",
        "duplicate_case_results_by_run_case",
        "succeeded_job_without_exactly_one_result",
    }


def test_reconciliation_rejects_run_counter_and_terminal_state_mismatch() -> None:
    reconciliation = reconcile_arm(
        expected_jobs=3,
        run_snapshot={
            "id": "run-1",
            "status": "succeeded",
            "total_jobs": 3,
            "succeeded_jobs": 3,
            "failed_jobs": 0,
            "cancelled_jobs": 0,
        },
        jobs=[
            {
                "id": "job-1",
                "run_id": "run-1",
                "case_id": "load-0000",
                "status": "succeeded",
                "attempt_count": 1,
            },
            {
                "id": "job-2",
                "run_id": "run-1",
                "case_id": "load-0001",
                "status": "succeeded",
                "attempt_count": 1,
            },
            {
                "id": "job-3",
                "run_id": "run-1",
                "case_id": "load-0002",
                "status": "running",
                "attempt_count": 1,
            },
        ],
        attempts=[
            {"job_id": "job-1", "attempt_number": 1},
            {"job_id": "job-2", "attempt_number": 1},
            {"job_id": "job-3", "attempt_number": 1},
        ],
        case_results=[
            {"job_id": "job-1", "run_id": "run-1", "case_id": "load-0000"},
            {"job_id": "job-2", "run_id": "run-1", "case_id": "load-0001"},
        ],
    )

    assert reconciliation["status_counts"] == {
        "queued": 0,
        "running": 1,
        "retry_wait": 0,
        "succeeded": 2,
        "failed": 0,
        "cancelling": 0,
        "cancelled": 0,
    }
    assert {violation["code"] for violation in reconciliation["violations"]} == {
        "run_counters_do_not_match_job_states",
        "unexplained_nonterminal_jobs",
        "final_run_status_inconsistent",
    }


def test_reconciliation_rejects_non_contiguous_attempt_sequence() -> None:
    reconciliation = reconcile_arm(
        expected_jobs=1,
        run_snapshot={
            "id": "run-1",
            "status": "succeeded",
            "total_jobs": 1,
            "succeeded_jobs": 1,
            "failed_jobs": 0,
            "cancelled_jobs": 0,
        },
        jobs=[
            {
                "id": "job-1",
                "run_id": "run-1",
                "case_id": "load-0000",
                "status": "succeeded",
                "attempt_count": 2,
            }
        ],
        attempts=[
            {
                "job_id": "job-1",
                "attempt_number": 1,
                "outcome": "failed",
                "retryable": True,
            },
            {
                "job_id": "job-1",
                "attempt_number": 3,
                "outcome": "succeeded",
                "retryable": None,
            },
        ],
        case_results=[{"job_id": "job-1", "run_id": "run-1", "case_id": "load-0000"}],
    )

    assert reconciliation["retry_count"] == 1
    assert reconciliation["attempt_sequences"] == {"job-1": [1, 3]}
    assert {violation["code"] for violation in reconciliation["violations"]} == {
        "attempt_sequence_mismatch"
    }


def test_reconciliation_rejects_missing_expected_job_rows() -> None:
    reconciliation = reconcile_arm(
        expected_jobs=500,
        run_snapshot={
            "id": "run-1",
            "status": "succeeded",
            "total_jobs": 1,
            "succeeded_jobs": 1,
            "failed_jobs": 0,
            "cancelled_jobs": 0,
        },
        jobs=[
            {
                "id": "job-1",
                "run_id": "run-1",
                "case_id": "load-0000",
                "status": "succeeded",
                "attempt_count": 1,
            }
        ],
        attempts=[{"job_id": "job-1", "attempt_number": 1}],
        case_results=[{"job_id": "job-1", "run_id": "run-1", "case_id": "load-0000"}],
    )

    assert {violation["code"] for violation in reconciliation["violations"]} == {
        "expected_job_count_mismatch"
    }


def test_reconciliation_rejects_arm_provenance_binding_mismatch() -> None:
    reconciliation = reconcile_arm(
        expected_jobs=0,
        expected_binding={
            "dataset_version_id": "dataset-version-1",
            "dataset_hash": "a" * 64,
            "source_commit": "b" * 40,
        },
        run_snapshot={
            "id": "run-1",
            "status": "partially_succeeded",
            "total_jobs": 0,
            "succeeded_jobs": 0,
            "failed_jobs": 0,
            "cancelled_jobs": 0,
            "dataset_version_id": "dataset-version-1",
            "dataset_hash": "c" * 64,
            "source_commit": "b" * 40,
        },
        jobs=[],
        attempts=[],
        case_results=[],
    )

    assert {violation["code"] for violation in reconciliation["violations"]} == {
        "arm_binding_mismatch"
    }
    assert reconciliation["binding_mismatches"] == {
        "dataset_hash": {"expected": "a" * 64, "observed": "c" * 64}
    }


def test_arm_summary_never_turns_missing_measurements_into_zero() -> None:
    reconciliation = {"valid_for_capacity_comparison": True, "retry_count": 0}

    summary = summarize_arm(
        reconciliation=reconciliation,
        measurement_seconds=2.0,
        end_to_end_ms=2100.0,
        jobs=[
            {
                "id": "job-1",
                "status": "succeeded",
                "created_at": "2026-07-29T12:00:00+00:00",
                "started_at": "2026-07-29T12:00:00.100000+00:00",
            },
            {
                "id": "job-2",
                "status": "succeeded",
                "created_at": "2026-07-29T12:00:00+00:00",
                "started_at": "2026-07-29T12:00:00.300000+00:00",
            },
        ],
        case_results=[{"latency_ms": 10}, {"latency_ms": 30}],
    )

    assert summary["throughput_cases_per_second"] == 1.0
    assert summary["successful_throughput_cases_per_second"] == 1.0
    assert summary["end_to_end_ms"] == 2100.0
    assert summary["case_latency_ms"] == {
        "evidence": "VERIFIED",
        "count": 2,
        "p50": 20.0,
        "p95": 29.0,
        "p99": 29.8,
    }
    assert summary["queue_wait_ms"]["p50"] == 200.0
    for missing_signal in (
        "claim_latency_ms",
        "db_transaction_latency_ms",
        "db_lock_wait",
        "cpu_rss",
        "postgres_connections",
        "redis_publish_failures",
    ):
        assert summary[missing_signal]["evidence"] == "UNKNOWN"
        assert summary[missing_signal].get("value") is None
    assert summary["stale_submission_rejection"] == {
        "evidence": "NOT_TESTED",
        "observed": 0,
    }


def test_arm_summary_promotes_only_supplied_collector_samples() -> None:
    summary = summarize_arm(
        reconciliation={"valid_for_capacity_comparison": True, "retry_count": 1},
        measurement_seconds=1.0,
        end_to_end_ms=1000.0,
        jobs=[],
        case_results=[],
        collector_samples={
            "claim_latency_ms": [1.0, 3.0],
            "db_transaction_latency_ms": [2.0, 6.0],
            "db_lock_waiting_connections": [0, 2, 1],
            "cpu_percent": [10.0, 30.0],
            "rss_bytes": [100, 150],
            "postgres_connections": [3, 5, 4],
            "redis_publish_failures": [0, 1],
        },
    )

    assert summary["claim_latency_ms"]["p50"] == 2.0
    assert summary["db_transaction_latency_ms"]["p95"] == 5.8
    assert summary["db_lock_wait"] == {
        "evidence": "DIRECTIONAL",
        "sample_count": 3,
        "samples_with_waiters": 2,
        "peak_waiting_connections": 2,
    }
    assert summary["cpu_rss"] == {
        "evidence": "VERIFIED",
        "sample_count": 2,
        "cpu_percent_peak": 30.0,
        "rss_bytes_peak": 150,
    }
    assert summary["postgres_connections"]["peak"] == 5
    assert summary["redis_publish_failures"]["delta"] == 1


def test_arm_summary_separates_retry_queue_wait_from_first_claim_wait() -> None:
    summary = summarize_arm(
        reconciliation={"valid_for_capacity_comparison": True, "retry_count": 1},
        measurement_seconds=1.0,
        end_to_end_ms=1000.0,
        jobs=[],
        case_results=[],
        attempts=[
            {
                "job_id": "job-1",
                "attempt_number": 1,
                "started_at": "2026-07-29T12:00:00+00:00",
                "finished_at": "2026-07-29T12:00:00.100000+00:00",
            },
            {
                "job_id": "job-1",
                "attempt_number": 2,
                "started_at": "2026-07-29T12:00:00.300000+00:00",
                "finished_at": "2026-07-29T12:00:00.400000+00:00",
            },
        ],
    )

    assert summary["retry_queue_wait_ms"] == {
        "evidence": "VERIFIED",
        "count": 1,
        "p50": 200.0,
        "p95": 200.0,
        "p99": 200.0,
    }


def test_aggregate_keeps_every_repetition_and_negative_scaling() -> None:
    aggregate = aggregate_arm_summaries(
        [
            {
                "arm": {
                    "arm_id": "w1-r1",
                    "workload": "io_latency_v1",
                    "workers": 1,
                    "repetition": 1,
                },
                "summary": {
                    "valid_for_capacity_comparison": True,
                    "throughput_cases_per_second": 10.0,
                },
            },
            {
                "arm": {
                    "arm_id": "w1-r2",
                    "workload": "io_latency_v1",
                    "workers": 1,
                    "repetition": 2,
                },
                "summary": {
                    "valid_for_capacity_comparison": True,
                    "throughput_cases_per_second": 12.0,
                },
            },
            {
                "arm": {
                    "arm_id": "w2-r1",
                    "workload": "io_latency_v1",
                    "workers": 2,
                    "repetition": 1,
                },
                "summary": {
                    "valid_for_capacity_comparison": True,
                    "throughput_cases_per_second": 9.0,
                },
            },
        ]
    )

    assert aggregate["groups"][0]["throughput_cases_per_second"] == {
        "points": [10.0, 12.0],
        "median": 11.0,
        "min": 10.0,
        "max": 12.0,
    }
    assert aggregate["groups"][1]["throughput_cases_per_second"] == {
        "points": [9.0],
        "median": 9.0,
        "min": 9.0,
        "max": 9.0,
    }
    assert aggregate["negative_scaling"] == [
        {
            "workload": "io_latency_v1",
            "from_workers": 1,
            "to_workers": 2,
            "median_throughput_change": -2.0,
        }
    ]
    assert aggregate["automatic_adoption_decision"] is None
