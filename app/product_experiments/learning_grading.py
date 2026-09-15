"""Bounded diagnostic graders and blind, descriptive review calibration."""

from __future__ import annotations

import json
from hashlib import sha256
from types import SimpleNamespace
from typing import Any, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.strict_json import decode_evidence_json
from app.product_experiments.evaluators import registered_evaluators
from app.reviews.agreement import calculate_agreement

Profile = Literal["normalized_exact_v1", "json_structural_v1"]
EvidenceCode = Literal[
    "NORMALIZED_EXACT_MATCH",
    "NORMALIZED_EXACT_MISMATCH",
    "JSON_STRUCTURAL_MATCH",
    "JSON_STRUCTURAL_MISMATCH",
    "INVALID_REFERENCE_JSON",
    "INVALID_ACTUAL_JSON",
]
MAX_TEXT_BYTES = 256_000
MAX_REVIEW_ITEMS = 1_000
MAX_PACKET_BYTES = 8_000_000


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, revalidate_instances="always"
    )


class GradeResult(_StrictModel):
    schema_version: Literal["learning_grade_v1"] = "learning_grade_v1"
    status: Literal["DIAGNOSTIC_ONLY"] = "DIAGNOSTIC_ONLY"
    grading_status: Literal["GRADED", "INVALID_REFERENCE"] = "GRADED"
    profile: Profile
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    passed: bool
    reason: str = Field(min_length=1)
    evidence_codes: list[EvidenceCode] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_score(self) -> Self:
        if self.score != float(self.passed):
            raise ValueError("binary diagnostic score and passed disagree")
        if (self.grading_status == "INVALID_REFERENCE") != (
            "INVALID_REFERENCE_JSON" in self.evidence_codes
        ):
            raise ValueError("invalid-reference evidence and grading status disagree")
        invalid = {"INVALID_REFERENCE_JSON", "INVALID_ACTUAL_JSON"}
        if self.profile == "json_structural_v1" and set(self.evidence_codes) <= invalid:
            if self.passed or len(set(self.evidence_codes)) != len(self.evidence_codes):
                raise ValueError("invalid JSON cannot pass or repeat evidence")
        else:
            prefix = (
                "NORMALIZED_EXACT" if self.profile == "normalized_exact_v1" else "JSON_STRUCTURAL"
            )
            expected = prefix + ("_MATCH" if self.passed else "_MISMATCH")
            if self.evidence_codes != [expected]:
                raise ValueError("evidence codes disagree with profile or binary result")
        return self


class DiagnosticGrader(Protocol):
    def grade(self, reference_answer: str, actual_answer: str) -> GradeResult: ...


class _NormalizedExactGrader:
    def grade(self, reference_answer: str, actual_answer: str) -> GradeResult:
        (evaluator,) = registered_evaluators(("reference_answer",))
        score = evaluator.evaluate(
            SimpleNamespace(reference_answer=reference_answer),
            SimpleNamespace(answer=actual_answer),
        )
        return GradeResult(
            profile="normalized_exact_v1",
            score=score,
            passed=bool(score),
            reason="Normalized text matches." if score else "Normalized text differs.",
            evidence_codes=["NORMALIZED_EXACT_MATCH" if score else "NORMALIZED_EXACT_MISMATCH"],
            limitations=["Text equality is not semantic correctness or official gate evidence."],
        )


class _JsonStructuralGrader:
    def grade(self, reference_answer: str, actual_answer: str) -> GradeResult:
        parsed: list[object] = []
        errors: list[EvidenceCode] = []
        for error_code, value in (
            ("INVALID_REFERENCE_JSON", reference_answer),
            ("INVALID_ACTUAL_JSON", actual_answer),
        ):
            try:
                parsed.append(decode_evidence_json(value))
            except (ValueError, RecursionError):
                errors.append(
                    "INVALID_REFERENCE_JSON"
                    if error_code == "INVALID_REFERENCE_JSON"
                    else "INVALID_ACTUAL_JSON"
                )
        score = 0.0
        if not errors:
            (evaluator,) = registered_evaluators(("tool_argument_validity",))
            score = evaluator.evaluate(
                SimpleNamespace(
                    expected_tool_calls=[SimpleNamespace(name="json", arguments=parsed[0])]
                ),
                SimpleNamespace(tool_calls=[SimpleNamespace(name="json", arguments=parsed[1])]),
            )
        code: EvidenceCode = "JSON_STRUCTURAL_MATCH" if score else "JSON_STRUCTURAL_MISMATCH"
        invalid_reference = "INVALID_REFERENCE_JSON" in errors
        return GradeResult(
            profile="json_structural_v1",
            score=score,
            passed=bool(score),
            grading_status="INVALID_REFERENCE" if invalid_reference else "GRADED",
            reason="Invalid strict JSON." if errors else "JSON structures compared.",
            evidence_codes=errors or [code],
            limitations=[
                "Structural equality is not semantic correctness or official gate evidence."
            ]
            + (
                [
                    "Invalid reference: zero is a sentinel, not a candidate failure; "
                    "exclude agreement."
                ]
                if invalid_reference
                else []
            ),
        )


_GRADERS: dict[str, DiagnosticGrader] = {
    "normalized_exact_v1": _NormalizedExactGrader(),
    "json_structural_v1": _JsonStructuralGrader(),
}


def grade_answer(reference_answer: str, actual_answer: str, *, profile: str) -> GradeResult:
    """Run a code-registered diagnostic profile; never load caller-supplied code."""
    _bounded_text(reference_answer)
    _bounded_text(actual_answer)
    if not isinstance(profile, str) or profile not in _GRADERS:
        raise ValueError(f"unknown grading profile: {profile}")
    return _GRADERS[profile].grade(reference_answer, actual_answer)


def _bounded_text(value: object) -> None:
    if not isinstance(value, str):
        raise ValueError("observation text fields must be strings")
    if len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError("observation text byte limit exceeded")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


def _digest(value: object) -> str:
    return sha256(_canonical(value)).hexdigest()


def observation_identity(row: dict[str, Any], *, profile: str) -> str:
    """Opaque versioned identity binds the source, answer, and diagnostic contract."""
    fields = ("case_id", "arm", "prompt", "reference_answer", "answer")
    for key in fields:
        _bounded_text(row.get(key))
    grade_answer(row["reference_answer"], row["answer"], profile=profile)
    identity = {key: _digest(row[key]) for key in fields}
    identity.update(
        profile=profile,
        grade_contract="learning_grade_v1",
        schema_version="learning_observation_v1",
    )
    return "obs_v1_" + _digest(identity)


class ReviewItem(_StrictModel):
    item_id: str = Field(pattern=r"^obs_v1_[0-9a-f]{64}$")
    prompt: str
    reference_answer: str
    answer: str
    profile: Profile


class ReviewPacket(_StrictModel):
    schema_version: Literal["learning_review_packet_v1"] = "learning_review_packet_v1"
    packet_hash: str
    rubric_instructions: str
    items: list[ReviewItem] = Field(max_length=MAX_REVIEW_ITEMS)

    @model_validator(mode="after")
    def bounded_packet(self) -> Self:
        for item in self.items:
            for value in (item.prompt, item.reference_answer, item.answer):
                _bounded_text(value)
        if len(_canonical(self.model_dump())) > MAX_PACKET_BYTES:
            raise ValueError("review packet byte limit exceeded")
        return self


_RUBRIC = (
    "Independently compare the answer with the question and reference. Label PASS only when "
    "the answer satisfies the requested content, FAIL for a substantive error, UNSURE when "
    "you cannot decide, or null when unreviewed. Do not infer an automated score. Supply "
    "reviewer_id, evidence_kind (HUMAN_DECLARED or SYNTHETIC), item_id and packet_hash. "
    "Synthetic examples are not human evidence; declarations are not authenticated."
)


def make_review_packet(rows: list[dict[str, Any]]) -> ReviewPacket:
    """Build a blind packet; no arm names, case IDs, or automated grades are exported."""
    if len(rows) > MAX_REVIEW_ITEMS:
        raise ValueError("review packet item limit exceeded")
    items = []
    for row in rows:
        profile = row.get("profile", "normalized_exact_v1")
        items.append(
            ReviewItem(
                item_id=observation_identity(row, profile=profile),
                profile=profile,
                prompt=row["prompt"],
                reference_answer=row["reference_answer"],
                answer=row["answer"],
            )
        )
    if len({item.item_id for item in items}) != len(items):
        raise ValueError("duplicate observation identity")
    items.sort(key=lambda item: item.item_id)
    packet = ReviewPacket(packet_hash="", rubric_instructions=_RUBRIC, items=items)
    return packet.model_copy(
        update={"packet_hash": _digest(packet.model_dump(exclude={"packet_hash"}))}
    )


EvidenceKind = Literal["HUMAN_DECLARED", "SYNTHETIC"]


class Review(_StrictModel):
    packet_hash: str
    item_id: str
    reviewer_id: str = Field(min_length=1, pattern=r"\S")
    evidence_kind: EvidenceKind
    label: Literal["PASS", "FAIL", "UNSURE"] | None


class CalibrationStats(_StrictModel):
    paired_labels: int
    ungradable_reviews: int
    exact_agreement: float | None
    cohen_kappa: float | None
    confusion_matrix: dict[str, int]


class CalibrationReport(CalibrationStats):
    schema_version: Literal["learning_calibration_v1"] = "learning_calibration_v1"
    status: Literal["DESCRIPTIVE_ONLY"] = "DESCRIPTIVE_ONLY"
    formal_status: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"
    human_verification: Literal["NOT_VERIFIED"] = "NOT_VERIFIED"
    packet_hash: str
    total_items: int
    submitted_reviews: int
    missing_reviews: int
    unsure_reviews: int
    null_reviews: int
    reviewer_ids: list[str]
    evidence_counts: dict[EvidenceKind, int]
    by_evidence_kind: dict[EvidenceKind, CalibrationStats]
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Descriptive agreement only; no threshold changes or official pass/fail decision.",
            "HUMAN_DECLARED is an unauthenticated declaration, not verified human evidence.",
            "Top-level agreement combines declared and synthetic labels; inspect each stratum.",
            "One review per item; missing, null, and UNSURE never count as agreeing pairs.",
        ]
    )


def _summary(reviews: list[Review], items: dict[str, ReviewItem]) -> CalibrationStats:
    pairs: list[tuple[str, str]] = []
    matrix = dict(true_pass=0, true_fail=0, false_pass=0, false_fail=0)
    ungradable = 0
    for review in reviews:
        if review.label not in ("PASS", "FAIL"):
            continue
        item = items[review.item_id]
        grade = grade_answer(item.reference_answer, item.answer, profile=item.profile)
        if grade.grading_status == "INVALID_REFERENCE":
            ungradable += 1
            continue
        automated = "PASS" if grade.passed else "FAIL"
        pairs.append((automated, review.label))
        key = ("true_" if automated == review.label else "false_") + automated.lower()
        matrix[key] += 1
    agreement = calculate_agreement(pairs)
    return CalibrationStats(
        paired_labels=agreement.paired_labels,
        ungradable_reviews=ungradable,
        exact_agreement=agreement.exact_agreement,
        cohen_kappa=agreement.cohen_kappa,
        confusion_matrix=matrix,
    )


def calibrate_reviews(
    packet: ReviewPacket | dict[str, Any], reviews: list[dict[str, Any]]
) -> CalibrationReport:
    """Describe review coverage and agreement, never certify human verification."""
    packet = ReviewPacket.model_validate(packet)
    if packet.packet_hash != _digest(packet.model_dump(exclude={"packet_hash"})):
        raise ValueError("stale or modified packet hash")
    if len(reviews) > MAX_REVIEW_ITEMS:
        raise ValueError("review item limit exceeded")
    parsed = [Review.model_validate(review) for review in reviews]
    items = {item.item_id: item for item in packet.items}
    if len(items) != len(packet.items):
        raise ValueError("duplicate packet item identity")
    seen: set[str] = set()
    for review in parsed:
        if review.packet_hash != packet.packet_hash:
            raise ValueError("stale review packet hash")
        if review.item_id not in items:
            raise ValueError("unknown review item identity")
        if review.item_id in seen:
            raise ValueError(
                "duplicate review item identity; only one review per item is supported"
            )
        seen.add(review.item_id)
    kinds: tuple[EvidenceKind, ...] = ("HUMAN_DECLARED", "SYNTHETIC")
    by_kind = {
        kind: [review for review in parsed if review.evidence_kind == kind] for kind in kinds
    }
    return CalibrationReport(
        packet_hash=packet.packet_hash,
        total_items=len(packet.items),
        submitted_reviews=len(parsed),
        missing_reviews=len(items) - len(parsed),
        unsure_reviews=sum(review.label == "UNSURE" for review in parsed),
        null_reviews=sum(review.label is None for review in parsed),
        reviewer_ids=sorted({review.reviewer_id for review in parsed}),
        evidence_counts={kind: len(values) for kind, values in by_kind.items()},
        by_evidence_kind={kind: _summary(values, items) for kind, values in by_kind.items()},
        **_summary(parsed, items).model_dump(),
    )
