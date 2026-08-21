from app.external_harness.quality_gate import (
    ShadowGateInputs,
    common_case_set,
    evaluate_shadow_gate,
    paired_bootstrap_delta,
)


def test_common_case_bootstrap_and_shadow_gate_are_fail_closed() -> None:
    baseline = {"a": 0.0, "b": 0.0, "left-only": 1.0}
    candidate = {"a": 1.0, "b": 0.0, "right-only": 1.0}

    common = common_case_set(baseline, candidate)
    interval = paired_bootstrap_delta(baseline, candidate, resamples=500, seed=7)

    assert common.common_ids == ("a", "b")
    assert common.left_only_ids == ("left-only",)
    assert common.right_only_ids == ("right-only",)
    assert interval.sample_count == 2
    assert interval.mean_delta == 0.5
    assert interval == paired_bootstrap_delta(baseline, candidate, resamples=500, seed=7)

    pending = evaluate_shadow_gate(
        ShadowGateInputs(
            automated_status="PASS",
            human_review_complete=False,
            trace_correlation_passed=True,
            failure_matrix_passed=True,
        )
    )
    blocked = evaluate_shadow_gate(
        ShadowGateInputs(
            automated_status="INPUT_BLOCKED",
            human_review_complete=False,
            trace_correlation_passed=True,
            failure_matrix_passed=True,
        )
    )
    failed = evaluate_shadow_gate(
        ShadowGateInputs(
            automated_status="PASS",
            human_review_complete=True,
            trace_correlation_passed=True,
            failure_matrix_passed=False,
        )
    )

    assert pending.status == "HUMAN_REVIEW_PENDING"
    assert blocked.status == "INPUT_BLOCKED"
    assert failed.status == "FAIL"
