"""Fail-closed verification for public aggregate evidence from external systems."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ExternalEvidenceError(ValueError):
    """External evidence is unreadable, stale, private, or outside its declared contract."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SourceCIReference(_StrictModel):
    run_id: int = Field(gt=0)
    url: str = Field(min_length=1, max_length=2_048)
    status: Literal["completed"]
    conclusion: Literal["success"]


class ExternalAggregateEvidenceReference(_StrictModel):
    schema_version: Literal["evalops.external-evidence-reference/1.0"]
    evidence_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$",
    )
    source_repository: str = Field(min_length=1, max_length=500)
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_ci: SourceCIReference
    artifact_path: str = Field(min_length=1, max_length=1_024)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_schema: str = Field(min_length=1, max_length=200)
    evidence_scope: str = Field(min_length=1, max_length=200)
    expected_case_count: int = Field(gt=0)
    expected_decision: str = Field(min_length=1, max_length=200)
    producing_code_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    allowed_claims: tuple[str, ...] = Field(min_length=1)
    forbidden_claims: tuple[str, ...] = Field(min_length=1)


_PRIVATE_PAYLOAD_KEYS = {
    "answers",
    "cases",
    "company_ids",
    "document_ids",
    "failures",
    "per_case",
    "questions",
    "source_paths",
}


def load_reference(path: Path) -> ExternalAggregateEvidenceReference:
    try:
        return ExternalAggregateEvidenceReference.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValueError) as error:
        raise ExternalEvidenceError(
            "external evidence reference is unreadable or invalid"
        ) from error


def _require_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExternalEvidenceError(f"evidence field must be an object: {field}")
    return value


def _require_exact_integer(mapping: dict[str, Any], field: str, expected: int) -> None:
    value = mapping.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value != expected:
        raise ExternalEvidenceError(f"evidence case-count mismatch: {field}")


def _require_number(
    mapping: dict[str, Any],
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = mapping.get(field)
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ExternalEvidenceError(f"evidence metric is missing or non-finite: {field}")
    numeric = float(value)
    if minimum is not None and numeric < minimum:
        raise ExternalEvidenceError(f"evidence metric is below its valid range: {field}")
    if maximum is not None and numeric > maximum:
        raise ExternalEvidenceError(f"evidence metric is above its valid range: {field}")
    return numeric


def _require_nonnegative_count(mapping: dict[str, Any], field: str) -> int:
    value = mapping.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExternalEvidenceError(f"evidence outcome count is invalid: {field}")
    return value


def _find_private_payload_keys(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in _PRIVATE_PAYLOAD_KEYS:
                found.add(key)
            found.update(_find_private_payload_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            found.update(_find_private_payload_keys(nested))
    return found


def verify_external_aggregate_evidence(
    reference: ExternalAggregateEvidenceReference,
    evidence_bytes: bytes,
) -> dict[str, Any]:
    digest = hashlib.sha256(evidence_bytes).hexdigest()
    if digest != reference.artifact_sha256:
        raise ExternalEvidenceError("external evidence SHA-256 mismatch")
    try:
        raw = json.loads(evidence_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExternalEvidenceError("external evidence is not valid UTF-8 JSON") from error
    evidence = _require_mapping(raw, "root")

    exact_fields = {
        "schema_version": reference.artifact_schema,
        "evaluation_scope": reference.evidence_scope,
        "decision": reference.expected_decision,
        "code_revision": reference.producing_code_sha,
        "protocol_sha256": reference.protocol_sha256,
    }
    for field, expected in exact_fields.items():
        if evidence.get(field) != expected:
            raise ExternalEvidenceError(f"external evidence identity mismatch: {field}")

    private_keys = _find_private_payload_keys(evidence)
    if private_keys:
        rendered_private_keys = ", ".join(sorted(private_keys))
        raise ExternalEvidenceError(
            "aggregate evidence unexpectedly contains private/per-case payload: "
            f"{rendered_private_keys}"
        )

    baseline = _require_mapping(evidence.get("baseline"), "baseline")
    candidate = _require_mapping(evidence.get("candidate"), "candidate")
    paired = _require_mapping(evidence.get("paired_outcomes"), "paired_outcomes")
    _require_exact_integer(baseline, "case_count", reference.expected_case_count)
    _require_exact_integer(candidate, "case_count", reference.expected_case_count)
    _require_exact_integer(paired, "case_count", reference.expected_case_count)

    baseline_hit = _require_number(baseline, "page_hit_at_5", minimum=0.0, maximum=1.0)
    candidate_hit = _require_number(candidate, "page_hit_at_5", minimum=0.0, maximum=1.0)
    baseline_ndcg = _require_number(baseline, "page_ndcg_at_5", minimum=0.0, maximum=1.0)
    candidate_ndcg = _require_number(candidate, "page_ndcg_at_5", minimum=0.0, maximum=1.0)
    baseline_p95 = _require_number(baseline, "latency_ms_p95", minimum=0.0)
    candidate_p95 = _require_number(candidate, "latency_ms_p95", minimum=0.0)
    latency_multiplier = _require_number(evidence, "p95_latency_multiplier", minimum=0.0)

    both_hit = _require_nonnegative_count(paired, "both_hit")
    candidate_only = _require_nonnegative_count(paired, "candidate_only_hit")
    baseline_only = _require_nonnegative_count(paired, "baseline_only_hit")
    both_miss = _require_nonnegative_count(paired, "both_miss")
    if both_hit + candidate_only + baseline_only + both_miss != reference.expected_case_count:
        raise ExternalEvidenceError("paired outcome counts do not sum to the declared case count")
    if _require_nonnegative_count(paired, "baseline_misses") != candidate_only + both_miss:
        raise ExternalEvidenceError("baseline miss count is inconsistent with paired outcomes")
    if _require_nonnegative_count(paired, "candidate_misses") != baseline_only + both_miss:
        raise ExternalEvidenceError("candidate miss count is inconsistent with paired outcomes")
    if not math.isclose(
        baseline_hit,
        (both_hit + baseline_only) / reference.expected_case_count,
        abs_tol=1e-12,
    ):
        raise ExternalEvidenceError("baseline Hit@5 is inconsistent with paired outcomes")
    if not math.isclose(
        candidate_hit,
        (both_hit + candidate_only) / reference.expected_case_count,
        abs_tol=1e-12,
    ):
        raise ExternalEvidenceError("candidate Hit@5 is inconsistent with paired outcomes")
    if baseline_p95 <= 0 or not math.isclose(
        latency_multiplier,
        candidate_p95 / baseline_p95,
        rel_tol=1e-12,
    ):
        raise ExternalEvidenceError("p95 latency multiplier is inconsistent with arm metrics")

    hit_interval = _require_mapping(
        evidence.get("page_hit_at_5_cluster_interval"),
        "page_hit_at_5_cluster_interval",
    )
    ndcg_interval = _require_mapping(
        evidence.get("page_ndcg_at_5_cluster_interval"),
        "page_ndcg_at_5_cluster_interval",
    )
    for name, interval, expected_delta in (
        ("page_hit_at_5_cluster_interval", hit_interval, candidate_hit - baseline_hit),
        ("page_ndcg_at_5_cluster_interval", ndcg_interval, candidate_ndcg - baseline_ndcg),
    ):
        lower = _require_number(interval, "lower_95")
        estimate = _require_number(interval, "estimate")
        upper = _require_number(interval, "upper_95")
        if not lower <= estimate <= upper or lower <= 0:
            raise ExternalEvidenceError(f"evidence interval is invalid or non-positive: {name}")
        if not math.isclose(estimate, expected_delta, abs_tol=1e-12):
            raise ExternalEvidenceError(
                f"evidence interval estimate disagrees with arm delta: {name}"
            )

    gate_checks = _require_mapping(evidence.get("gate_checks"), "gate_checks")
    if not gate_checks or any(value is not True for value in gate_checks.values()):
        raise ExternalEvidenceError("external evidence contains a missing or failed source gate")
    claim_boundary = evidence.get("claim_boundary")
    if (
        not isinstance(claim_boundary, list)
        or not claim_boundary
        or any(not isinstance(item, str) or not item for item in claim_boundary)
    ):
        raise ExternalEvidenceError("external evidence has no usable claim boundary")

    return {
        "schema_version": "evalops.external-evidence-verification/1.0",
        "evidence_id": reference.evidence_id,
        "status": "AGGREGATE_EVIDENCE_VERIFIED",
        "verification_scope": "SOURCE_BYTES_AND_DECLARED_CLAIM_CONTRACT",
        "source": {
            "repository": reference.source_repository,
            "sha": reference.source_sha,
            "ci": reference.source_ci.model_dump(mode="json"),
            "ci_live_status": "REFERENCE_BOUND_REQUIRES_OUT_OF_BAND_VERIFICATION",
            "artifact_path": reference.artifact_path,
            "artifact_sha256": digest,
            "artifact_schema": reference.artifact_schema,
            "producing_code_sha": reference.producing_code_sha,
            "protocol_sha256": reference.protocol_sha256,
        },
        "evidence_scope": reference.evidence_scope,
        "case_count": reference.expected_case_count,
        "decision": reference.expected_decision,
        "metrics": {
            "baseline": baseline,
            "candidate": candidate,
            "paired_outcomes": paired,
            "company_macro": evidence.get("company_macro"),
            "page_hit_at_5_cluster_interval": evidence.get("page_hit_at_5_cluster_interval"),
            "page_ndcg_at_5_cluster_interval": evidence.get("page_ndcg_at_5_cluster_interval"),
            "p95_latency_multiplier": latency_multiplier,
        },
        "source_gate_checks": gate_checks,
        "source_claim_boundary": claim_boundary,
        "allowed_claims": list(reference.allowed_claims),
        "forbidden_claims": list(reference.forbidden_claims),
        "private_or_per_case_payload_present": False,
        "formal_case_result_status": "INPUT_REQUIRED",
        "formal_ab_status": "NOT_RUN_BY_EVALOPS",
        "formal_quality_claim_allowed": False,
        "human_review_status": "PENDING",
        "production_ready": False,
    }


def verify_external_aggregate_evidence_files(
    reference_path: Path,
    evidence_path: Path,
) -> dict[str, Any]:
    reference = load_reference(reference_path)
    try:
        evidence_bytes = evidence_path.read_bytes()
    except OSError as error:
        raise ExternalEvidenceError("external evidence artifact is unreadable") from error
    return verify_external_aggregate_evidence(reference, evidence_bytes)


__all__ = [
    "ExternalAggregateEvidenceReference",
    "ExternalEvidenceError",
    "load_reference",
    "verify_external_aggregate_evidence",
    "verify_external_aggregate_evidence_files",
]
