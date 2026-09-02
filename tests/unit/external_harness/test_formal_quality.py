from __future__ import annotations

import json

import pytest

from app.external_harness.formal_quality import (
    FormalArmResult,
    FormalCaseMeasurement,
    FormalQualityPolicy,
    assess_formal_quality,
    build_blinded_review_packet,
)

CATEGORIES = (
    "basic",
    "semantic",
    "multi_document",
    "conflicting_information",
    "not_found",
)


def _arm(*, candidate: bool, count: int = 100) -> FormalArmResult:
    cases = []
    for index in range(count):
        category = CATEGORIES[index % len(CATEGORIES)]
        cases.append(
            FormalCaseMeasurement(
                case_id=f"case-{index:03d}",
                category=category,
                prompt=f"Question {index}",
                task_success=1.0 if candidate else 0.0,
                citation_correctness=1.0 if candidate else 0.0,
                tool_error_rate=0.0 if candidate else 0.1,
                latency_ms=110.0 if candidate else 100.0,
                cost_usd=0.011 if candidate else 0.01,
                answer=f"Answer {index} variant {1 if candidate else 0}",
                citations=[{"source_id": f"source-{index}"}],
            )
        )
    return FormalArmResult(
        schema_version="formal-agent-quality-arm/1.0",
        arm="candidate" if candidate else "baseline",
        source_sha=("b" if candidate else "a") * 40,
        dataset_sha256="d" * 64,
        cases=cases,
    )


def _policy() -> FormalQualityPolicy:
    return FormalQualityPolicy(
        schema_version="formal-agent-quality-policy/1.0",
        minimum_common_cases=100,
        minimum_cases_per_category=10,
        required_categories=CATEGORIES,
        bootstrap_resamples=500,
        bootstrap_seed=20260902,
        task_success_ci_lower_min=0.0,
        citation_correctness_ci_lower_min=-0.02,
        tool_error_rate_ci_upper_max=0.02,
        latency_p95_relative_delta_max=0.25,
        cost_mean_relative_delta_max=0.25,
        require_exact_case_set=True,
    )


def test_formal_quality_gate_emits_all_required_metrics_and_exact_identities() -> None:
    assessment = assess_formal_quality(
        baseline=_arm(candidate=False),
        candidate=_arm(candidate=True),
        policy=_policy(),
        evalops_sha="e" * 40,
        trace_status="PASS",
        failure_matrix_status="PASS",
    )

    assert assessment.status == "PASS"
    assert assessment.decision.outcome == "PASS"
    assert assessment.decision.common_case_count == 100
    assert assessment.decision.per_category_counts == {category: 20 for category in CATEGORIES}
    assert set(assessment.metrics) == {
        "task_success_delta",
        "citation_correctness_delta",
        "tool_error_rate_delta",
        "latency_p95_delta",
        "cost_delta",
    }
    assert assessment.metrics["latency_p95_delta"].relative_delta == pytest.approx(0.1)
    assert assessment.metrics["cost_delta"].relative_delta == pytest.approx(0.1)
    assert len(assessment.decision.automated_metrics_digest) == 64


def test_formal_quality_gate_fails_closed_on_insufficient_or_drifting_inputs() -> None:
    insufficient = assess_formal_quality(
        baseline=_arm(candidate=False, count=20),
        candidate=_arm(candidate=True, count=20),
        policy=_policy(),
        evalops_sha="e" * 40,
        trace_status="PASS",
        failure_matrix_status="PASS",
    )
    assert insufficient.status == "INSUFFICIENT_EVIDENCE"
    assert insufficient.decision.outcome == "INSUFFICIENT_EVIDENCE"

    candidate = _arm(candidate=True)
    candidate.cases[0] = candidate.cases[0].model_copy(update={"prompt": "drifted question"})
    with pytest.raises(ValueError, match="prompt/category drift"):
        assess_formal_quality(
            baseline=_arm(candidate=False),
            candidate=candidate,
            policy=_policy(),
            evalops_sha="e" * 40,
            trace_status="PASS",
            failure_matrix_status="PASS",
        )

    with pytest.raises(ValueError, match="dataset_sha256"):
        FormalArmResult(
            schema_version="formal-agent-quality-arm/1.0",
            arm="candidate",
            source_sha="b" * 40,
            dataset_sha256="not-a-digest",
            cases=_arm(candidate=True).cases,
        )


def test_blinded_review_packet_hides_arm_identity_and_seals_mapping() -> None:
    packet, mapping = build_blinded_review_packet(
        baseline=_arm(candidate=False),
        candidate=_arm(candidate=True),
        blinding_key=bytes.fromhex("11" * 32),
    )

    encoded_packet = json.dumps(packet, sort_keys=True)
    assert "baseline" not in encoded_packet
    assert "candidate" not in encoded_packet
    assert packet["schema_version"] == "formal-agent-human-review-packet/1.0"
    assert len(packet["cases"]) == 100
    assert mapping["schema_version"] == "formal-agent-human-review-map/1.0"
    assert len(mapping["packet_sha256"]) == 64
    assert {item["A"] for item in mapping["case_mapping"]} == {"baseline", "candidate"}
    assert all(set(item["answers"]) == {"A", "B"} for item in packet["cases"])
