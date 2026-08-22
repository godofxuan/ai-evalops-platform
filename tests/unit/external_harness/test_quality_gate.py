import pytest

from app.external_harness.quality_gate import (
    EvidencePolicy,
    FormalEvidenceDecision,
    InsufficientEvidenceError,
    assess_evidence_sufficiency,
    common_case_set,
    evaluate_shadow_gate,
    paired_bootstrap_delta,
)


def _decision(**overrides: object) -> FormalEvidenceDecision:
    values: dict[str, object] = {
        "dataset_hash": "1" * 64,
        "policy_hash": "2" * 64,
        "baseline_sha": "a" * 40,
        "candidate_sha": "b" * 40,
        "evalops_sha": "c" * 40,
        "common_case_ids_hash": "3" * 64,
        "common_case_count": 100,
        "per_category_counts": {"grounded": 100},
        "a_only_count": 0,
        "b_only_count": 0,
        "required_category_coverage": ("grounded",),
        "minimum_common_cases": 100,
        "minimum_per_category": 10,
        "bootstrap_method": "paired-percentile-bootstrap",
        "automated_metrics_digest": "4" * 64,
        "automated_metrics_passed": True,
        "human_review_status": "PENDING",
        "trace_status": "PASS",
        "failure_matrix_status": "PASS",
        "formal_ab_eligible": True,
        "evidence_sufficiency": "SUFFICIENT",
    }
    values.update(overrides)
    return FormalEvidenceDecision(**values)  # type: ignore[arg-type]


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

    pending = evaluate_shadow_gate(_decision())
    blocked = evaluate_shadow_gate(_decision(formal_ab_eligible=False))
    failed = evaluate_shadow_gate(
        _decision(human_review_status="COMPLETE", failure_matrix_status="FAIL")
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
        _decision(
            common_case_count=9,
            per_category_counts={"grounded": 9},
            evidence_sufficiency="INSUFFICIENT_EVIDENCE",
            human_review_status="COMPLETE",
        )
    )
    segmented_failure = evaluate_shadow_gate(
        _decision(human_review_status="COMPLETE", required_segments_passed=False)
    )
    assert insufficient.status == "INSUFFICIENT_EVIDENCE"
    assert segmented_failure.status == "FAIL"
    assert segmented_failure.reasons == ("required_segment_failed",)


def test_contract_result_cannot_be_promoted_to_shadow_pass() -> None:
    contract = _decision(
        formal_ab_eligible=False,
        contract_verified=True,
        common_case_count=20,
        per_category_counts={"mechanism": 20},
        required_category_coverage=("mechanism",),
        human_review_status="COMPLETE",
    )

    assert contract.outcome == "CONTRACT_VERIFIED"
    decision = evaluate_shadow_gate(contract)
    assert decision.status == "INPUT_BLOCKED"
    assert decision.reasons == ("contract_verified_not_formal_ab",)


def test_evidence_binding_rejects_non_exact_hashes() -> None:
    with pytest.raises(ValueError, match="dataset_hash"):
        _decision(dataset_hash="not-a-digest")
    with pytest.raises(ValueError, match="candidate_sha"):
        _decision(candidate_sha="b" * 39)
