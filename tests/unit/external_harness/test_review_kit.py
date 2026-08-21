import pytest

from app.external_harness.review_kit import ReviewRow, validate_completed_reviews


def test_review_completion_requires_two_distinct_real_reviewer_identities() -> None:
    base = {
        "packet_id": "blind-packet-v1",
        "case_id": "case-1",
        "groundedness": 2,
        "citation_correctness": 2,
        "tool_correctness": 2,
        "safety_refusal": 2,
        "overall": "pass",
    }
    rows = [
        ReviewRow(reviewer_id=reviewer_id, answer_label=answer_label, **base)
        for reviewer_id in ("reviewer-alice", "reviewer-bob")
        for answer_label in ("A", "B")
    ]

    summary = validate_completed_reviews(rows, expected_case_ids={"case-1"})

    assert summary.complete is True
    assert summary.reviewer_count == 2
    assert summary.exact_agreement == 1.0
    assert summary.cohen_kappa is None

    with pytest.raises(ValueError, match="distinct"):
        validate_completed_reviews(
            [rows[0], rows[1], rows[0].model_copy(), rows[1].model_copy()],
            expected_case_ids={"case-1"},
        )
