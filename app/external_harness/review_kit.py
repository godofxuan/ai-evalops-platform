"""Validation boundary for blinded reviews; unit fixtures never count as human evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.reviews.agreement import calculate_agreement


class ReviewRow(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    packet_id: str = Field(min_length=1, max_length=200)
    reviewer_id: str = Field(min_length=3, max_length=200)
    case_id: str = Field(min_length=1, max_length=200)
    answer_label: Literal["A", "B"]
    groundedness: int = Field(ge=0, le=2)
    citation_correctness: int = Field(ge=0, le=2)
    tool_correctness: int = Field(ge=0, le=2)
    safety_refusal: int = Field(ge=0, le=2)
    overall: Literal["pass", "fail", "needs_adjudication"]
    notes: str = Field(default="", max_length=2000)


@dataclass(frozen=True, slots=True)
class CompletedReviewSummary:
    complete: bool
    packet_id: str
    reviewer_count: int
    case_count: int
    exact_agreement: float | None
    cohen_kappa: float | None
    adjudication_case_ids: tuple[str, ...]


def validate_completed_reviews(
    rows: list[ReviewRow],
    *,
    expected_case_ids: set[str],
) -> CompletedReviewSummary:
    if not expected_case_ids:
        raise ValueError("expected case set cannot be empty")
    packet_ids = {row.packet_id for row in rows}
    if len(packet_ids) != 1:
        raise ValueError("reviews must reference exactly one blinded packet")
    reviewer_ids = {row.reviewer_id for row in rows}
    if len(reviewer_ids) != 2:
        raise ValueError("completion requires exactly two distinct reviewer identities")
    if {row.case_id for row in rows} != expected_case_ids:
        raise ValueError("review rows must exactly cover the frozen expected case set")

    by_answer: dict[tuple[str, str], list[ReviewRow]] = defaultdict(list)
    for row in rows:
        by_answer[(row.case_id, row.answer_label)].append(row)
    expected_answers = {(case_id, label) for case_id in expected_case_ids for label in ("A", "B")}
    if set(by_answer) != expected_answers or any(
        len(answer_rows) != 2 or {row.reviewer_id for row in answer_rows} != reviewer_ids
        for answer_rows in by_answer.values()
    ):
        raise ValueError("each case requires A and B ratings from both distinct reviewers")

    pairs: list[tuple[Hashable, Hashable]] = []
    adjudication = set()
    for (case_id, _answer_label), answer_rows in sorted(by_answer.items()):
        ordered = sorted(answer_rows, key=lambda item: item.reviewer_id)
        labels: tuple[Hashable, Hashable] = (ordered[0].overall, ordered[1].overall)
        pairs.append(labels)
        if labels[0] != labels[1] or "needs_adjudication" in labels:
            adjudication.add(case_id)
    agreement = calculate_agreement(pairs)
    return CompletedReviewSummary(
        complete=True,
        packet_id=next(iter(packet_ids)),
        reviewer_count=2,
        case_count=len(expected_case_ids),
        exact_agreement=agreement.exact_agreement,
        cohen_kappa=agreement.cohen_kappa,
        adjudication_case_ids=tuple(sorted(adjudication)),
    )


__all__ = ["CompletedReviewSummary", "ReviewRow", "validate_completed_reviews"]
