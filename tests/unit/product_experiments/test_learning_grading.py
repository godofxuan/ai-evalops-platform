from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.product_experiments import learning_grading as grading
from app.product_experiments.learning_grading import GradeResult, grade_answer


def test_normalized_exact_is_a_versioned_diagnostic_not_an_official_gate() -> None:
    result = grade_answer("  HELLO\nworld ", "hello WORLD", profile="normalized_exact_v1")
    assert result.score == 1.0
    assert result.passed is True
    assert result.schema_version == "learning_grade_v1"
    assert result.status == "DIAGNOSTIC_ONLY"
    assert result.model_dump(mode="json")["evidence_codes"] == ["NORMALIZED_EXACT_MATCH"]
    assert result.limitations


@pytest.mark.parametrize(
    "reference,actual,passed",
    [
        ('{"a":1,"b":[false]}', '{"b":[false],"a":1.0}', True),
        ('{"a":true}', '{"a":1}', False),
        ("[1,2]", "[2,1]", False),
        ('{"a":1}', '{"a":0,"a":1}', False),
        ('{"a":0,"a":1}', '{"a":1}', False),
        ("NaN", "NaN", False),
        ("Infinity", "Infinity", False),
        ("1e999", "1e999", False),
    ],
)
def test_json_structural_grading_is_strict_and_type_aware(
    reference: str, actual: str, passed: bool
) -> None:
    result = grade_answer(reference, actual, profile="json_structural_v1")
    assert result.passed is passed
    assert result.score == float(passed)
    assert result.reason


def test_grading_rejects_unregistered_profiles_and_inconsistent_results() -> None:
    with pytest.raises(ValueError, match="unknown grading profile"):
        grade_answer("x", "x", profile="python:uploaded_code")
    with pytest.raises(ValueError, match="strings"):
        grade_answer("x", 1, profile="normalized_exact_v1")  # type: ignore[arg-type]
    payload = grade_answer("x", "x", profile="normalized_exact_v1").model_dump()
    for update in ({"score": "1"}, {"passed": False}, {"evidence_codes": ["INVENTED"]}):
        with pytest.raises(ValidationError):
            GradeResult.model_validate(payload | update)


def _row(**changes: str) -> dict[str, str]:
    return (
        dict(
            case_id="case-1",
            arm="candidate",
            prompt="question",
            reference_answer="yes",
            answer="yes",
        )
        | changes
    )


def test_review_packet_is_blind_stable_and_binds_every_observation_field() -> None:
    row = _row()
    packet = grading.make_review_packet([row])
    item = packet.model_dump(mode="json")["items"][0]
    assert set(item) == {"item_id", "prompt", "reference_answer", "answer", "profile"}
    assert packet.rubric_instructions
    assert packet == grading.make_review_packet([row])
    assert item["item_id"] == grading.observation_identity(row, profile="normalized_exact_v1")
    for key in row:
        changed = grading.make_review_packet([row | {key: "changed"}])
        assert changed.items[0].item_id != item["item_id"]
        assert changed.packet_hash != packet.packet_hash
    changed = grading.make_review_packet([row | {"profile": "json_structural_v1"}])
    assert changed.items[0].item_id != item["item_id"]
    with pytest.raises(ValueError, match="duplicate"):
        grading.make_review_packet([row, row])


def test_absent_human_reviews_have_zero_coverage_and_no_agreement_claim() -> None:
    packet = grading.make_review_packet([_row(), _row(case_id="case-2")])
    report = grading.calibrate_reviews(packet, [])
    assert report.total_items == report.missing_reviews == 2
    assert report.paired_labels == report.submitted_reviews == 0
    assert report.exact_agreement is report.cohen_kappa is None
    assert report.status == "DESCRIPTIVE_ONLY"
    assert report.formal_status == "NOT_EVALUATED"
    assert report.human_verification == "NOT_VERIFIED"


@pytest.mark.parametrize(
    "mutation",
    [
        "stale_hash",
        "unknown_id",
        "duplicate_review",
        "missing_reviewer",
        "blank_reviewer",
        "missing_kind",
        "missing_label",
        "invalid_label",
        "extra_field",
        "modified_packet",
    ],
)
def test_calibration_rejects_unbound_ambiguous_or_undeclared_reviews(mutation: str) -> None:
    packet = grading.make_review_packet([_row()])
    review: dict[str, object] = dict(
        item_id=packet.items[0].item_id,
        packet_hash=packet.packet_hash,
        reviewer_id="synthetic-example",
        evidence_kind="SYNTHETIC",
        label="PASS",
    )
    reviews = [review]
    if mutation == "stale_hash":
        review["packet_hash"] = "0" * 64
    elif mutation == "unknown_id":
        review["item_id"] = "obs_v1_" + "0" * 64
    elif mutation == "duplicate_review":
        reviews.append(review)
    elif mutation == "missing_reviewer":
        del review["reviewer_id"]
    elif mutation == "blank_reviewer":
        review["reviewer_id"] = " "
    elif mutation == "missing_kind":
        del review["evidence_kind"]
    elif mutation == "missing_label":
        del review["label"]
    elif mutation == "invalid_label":
        review["label"] = True
    elif mutation == "extra_field":
        review["trusted"] = True
    elif mutation == "modified_packet":
        packet = packet.model_copy(update={"rubric_instructions": "Changed rubric"})
    with pytest.raises(ValueError):
        grading.calibrate_reviews(packet, reviews)


def test_calibration_accounts_for_abstentions_and_stratifies_synthetic_labels() -> None:
    rows = [
        _row(case_id=str(index), answer="yes" if index % 2 == 0 else "no") for index in range(7)
    ]
    packet = grading.make_review_packet(rows)
    index_by_id = {
        grading.observation_identity(row, profile="normalized_exact_v1"): index
        for index, row in enumerate(rows)
    }
    reviews = []
    # Each matrix cell once, plus UNSURE, explicit null, and one missing review.
    for item in packet.items:
        index = index_by_id[item.item_id]
        if index < 6:
            reviews.append(
                dict(
                    item_id=item.item_id,
                    packet_hash=packet.packet_hash,
                    reviewer_id="reviewer-1",
                    evidence_kind="HUMAN_DECLARED" if index < 2 else "SYNTHETIC",
                    label=["PASS", "FAIL", "FAIL", "PASS", "UNSURE", None][index],
                )
            )
    report = grading.calibrate_reviews(packet.model_dump(mode="json"), reviews)
    assert report.total_items == 7
    assert report.submitted_reviews == 6
    assert report.missing_reviews == report.unsure_reviews == report.null_reviews == 1
    assert report.paired_labels == 4
    assert report.confusion_matrix == dict(true_pass=1, true_fail=1, false_pass=1, false_fail=1)
    assert report.exact_agreement == 0.5
    assert report.cohen_kappa == 0.0
    assert report.by_evidence_kind["HUMAN_DECLARED"].exact_agreement == 1.0
    assert report.by_evidence_kind["SYNTHETIC"].exact_agreement == 0.0
    assert report.evidence_counts == {"HUMAN_DECLARED": 2, "SYNTHETIC": 4}
    assert report.formal_status == "NOT_EVALUATED"


def test_diagnostic_inputs_and_packets_are_bounded() -> None:
    with pytest.raises(ValueError, match="byte limit"):
        grade_answer("x", "x" * 256_001, profile="normalized_exact_v1")
    deep = "[" * 65 + "0" + "]" * 65
    assert not grade_answer("[]", deep, profile="json_structural_v1").passed
    with pytest.raises(ValueError, match="item limit"):
        grading.make_review_packet([_row(case_id=str(index)) for index in range(1001)])
    with pytest.raises(ValueError, match="byte limit"):
        grading.make_review_packet(
            [_row(case_id=str(index), prompt="x" * 100_000) for index in range(81)]
        )


def test_invalid_reference_is_not_a_candidate_failure_or_agreement_pair() -> None:
    result = grade_answer('{"x":1,"x":2}', '{"x":2}', profile="json_structural_v1")
    assert result.grading_status == "INVALID_REFERENCE"
    assert "INVALID_REFERENCE_JSON" in result.evidence_codes
    assert any("not a candidate failure" in text for text in result.limitations)
    packet = grading.make_review_packet(
        [_row(reference_answer="not JSON", answer="{}", profile="json_structural_v1")]
    )
    report = grading.calibrate_reviews(
        packet,
        [
            dict(
                item_id=packet.items[0].item_id,
                packet_hash=packet.packet_hash,
                reviewer_id="synthetic-example",
                evidence_kind="SYNTHETIC",
                label="FAIL",
            )
        ],
    )
    assert report.ungradable_reviews == 1
    assert report.paired_labels == 0
    assert report.exact_agreement is None
    assert not any(report.confusion_matrix.values())


@pytest.mark.parametrize(
    "changes",
    [
        {"profile": "json_structural_v1"},
        {"score": 0.0, "passed": False},
        {"evidence_codes": ["INVALID_ACTUAL_JSON"]},
    ],
)
def test_grade_evidence_must_agree_with_profile_and_binary_result(
    changes: dict[str, object],
) -> None:
    payload = grade_answer("yes", "yes", profile="normalized_exact_v1").model_dump()
    with pytest.raises(ValidationError):
        GradeResult.model_validate(payload | changes)
