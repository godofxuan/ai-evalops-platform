import pytest

from app.external_harness.quality_gate import (
    EvidencePolicy,
    InsufficientEvidenceError,
    ShadowGateInputs,
    assess_evidence_sufficiency,
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


def test_formal_evidence_requires_real_sample_and_category_coverage() -> None:
    with pytest.raises(InsufficientEvidenceError, match="at least 2"):
        paired_bootstrap_delta({"one": 0.0}, {"one": 1.0})

    baseline = {f"case-{index}": 0.0 for index in range(9)}
    candidate = {
        **{f"case-{index}": 1.0 for index in range(9)},
        "right-only": 1.0,
    }
    sufficiency = assess_evidence_sufficiency(
        baseline,
        candidate,
        category_by_case={f"case-{index}": "grounded" for index in range(9)},
        policy=EvidencePolicy(
            minimum_common_cases=100,
            minimum_cases_per_category=10,
            required_categories=("grounded", "tool-use"),
        ),
    )

    assert sufficiency.status == "INSUFFICIENT_EVIDENCE"
    assert sufficiency.common_case_count == 9
    assert sufficiency.right_only_ids == ("right-only",)
    assert "minimum_common_cases_not_met" in sufficiency.reasons
    assert "category_under_minimum:grounded" in sufficiency.reasons
    assert "category_under_minimum:tool-use" in sufficiency.reasons

    insufficient = evaluate_shadow_gate(
        ShadowGateInputs(
            automated_status="INSUFFICIENT_EVIDENCE",
            human_review_complete=True,
            trace_correlation_passed=True,
            failure_matrix_passed=True,
        )
    )
    segmented_failure = evaluate_shadow_gate(
        ShadowGateInputs(
            automated_status="PASS",
            human_review_complete=True,
            trace_correlation_passed=True,
            failure_matrix_passed=True,
            required_segments_passed=False,
        )
    )
    assert insufficient.status == "INSUFFICIENT_EVIDENCE"
    assert segmented_failure.status == "FAIL"
    assert segmented_failure.reasons == ("required_segment_failed",)
