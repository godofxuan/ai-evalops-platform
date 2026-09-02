"""Verify a producer-native aggregate-only evidence contract without creating case rows."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.product_experiments.external_evidence import ExternalEvidenceError, SourceCIReference


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or "\\" in value or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("path must be normalized repository-relative POSIX")
    return value


class AggregateContractPin(_StrictModel):
    schema_version: Literal["evalops.aggregate-contract-pin/1.0"]
    publisher_repository: str = Field(min_length=1, max_length=500)
    publisher_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    publisher_ci: SourceCIReference
    reference_path: str = Field(min_length=1, max_length=1_024)
    reference_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    _reference_path = field_validator("reference_path")(_safe_path)


class ProducerAggregateReference(_StrictModel):
    schema_version: Literal["enterprise-rag.aggregate-evidence-reference/1.0"]
    evidence_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    source_repository: str = Field(min_length=1, max_length=500)
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_ci: SourceCIReference
    artifact_path: str = Field(min_length=1, max_length=1_024)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_schema: str = Field(min_length=1, max_length=200)
    producing_code_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_scope: str = Field(min_length=1, max_length=500)
    case_count: int = Field(gt=0)
    decision: str = Field(min_length=1, max_length=200)
    allowed_claims: tuple[str, ...] = Field(min_length=1)
    forbidden_claims: tuple[str, ...] = Field(min_length=1)
    payload_granularity: Literal["aggregate_only"]
    formal_case_results: Literal["INPUT_REQUIRED"]
    contains_private_case_payload: Literal[False]

    _artifact_path = field_validator("artifact_path")(_safe_path)

    @model_validator(mode="after")
    def validate_ci_url(self) -> ProducerAggregateReference:
        if not self.source_ci.url.startswith(self.source_repository + "/actions/runs/"):
            raise ValueError("source CI URL does not belong to source repository")
        if not self.source_ci.url.endswith(f"/{self.source_ci.run_id}"):
            raise ValueError("source CI run ID does not match its URL")
        return self


_PRIVATE_KEYS = {
    "answer",
    "answers",
    "article_text",
    "case_id",
    "case_ids",
    "company_ids",
    "document_ids",
    "per_case",
    "question",
    "questions",
    "source_path",
    "source_paths",
    "text",
}


def _read_inside(root: Path, relative: str) -> bytes:
    resolved_root = root.resolve()
    path = (resolved_root / Path(*PurePosixPath(relative).parts)).resolve()
    try:
        path.relative_to(resolved_root)
    except ValueError as error:
        raise ExternalEvidenceError("aggregate contract path escapes producer root") from error
    try:
        return path.read_bytes()
    except OSError as error:
        raise ExternalEvidenceError("aggregate contract file is unreadable") from error


def _private_keys(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in _PRIVATE_KEYS:
                found.add(str(key))
            found.update(_private_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_private_keys(child))
    return found


def verify_aggregate_contract(
    pin: AggregateContractPin,
    *,
    producer_root: Path,
    observed_publisher_sha: str,
) -> dict[str, Any]:
    if observed_publisher_sha != pin.publisher_sha:
        raise ExternalEvidenceError("producer checkout SHA does not match pinned publisher SHA")
    reference_bytes = _read_inside(producer_root, pin.reference_path)
    reference_digest = hashlib.sha256(reference_bytes).hexdigest()
    if reference_digest != pin.reference_sha256:
        raise ExternalEvidenceError("producer aggregate reference SHA-256 mismatch")
    try:
        reference = ProducerAggregateReference.model_validate_json(reference_bytes)
    except ValueError as error:
        raise ExternalEvidenceError("producer aggregate reference is invalid") from error
    if reference.source_repository != pin.publisher_repository:
        raise ExternalEvidenceError("producer repository identity mismatch")
    artifact_bytes = _read_inside(producer_root, reference.artifact_path)
    artifact_digest = hashlib.sha256(artifact_bytes).hexdigest()
    if artifact_digest != reference.artifact_sha256:
        raise ExternalEvidenceError("producer aggregate artifact SHA-256 mismatch")
    try:
        payload = json.loads(artifact_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExternalEvidenceError("producer aggregate artifact is invalid JSON") from error
    if not isinstance(payload, dict):
        raise ExternalEvidenceError("producer aggregate artifact must be an object")
    private = _private_keys(payload)
    if private:
        raise ExternalEvidenceError("aggregate artifact contains private/per-case payload")
    if payload.get("decision") != reference.decision:
        raise ExternalEvidenceError("aggregate decision does not match producer reference")
    protocol_digests = {
        value
        for key, value in payload.items()
        if (key == "protocol_sha256" or key.endswith("_protocol_sha256")) and isinstance(value, str)
    }
    if reference.protocol_sha256 not in protocol_digests:
        raise ExternalEvidenceError("aggregate protocol does not match producer reference")
    boundary = payload.get("claim_boundary")
    if (
        not isinstance(boundary, list)
        or not boundary
        or not all(isinstance(item, str) and item for item in boundary)
    ):
        raise ExternalEvidenceError("aggregate artifact has no usable claim boundary")
    return {
        "schema_version": "evalops.aggregate-contract-verification/1.0",
        "status": "AGGREGATE_EVIDENCE_VERIFIED",
        "evidence_id": reference.evidence_id,
        "publisher": {
            "repository": pin.publisher_repository,
            "sha": pin.publisher_sha,
            "ci": pin.publisher_ci.model_dump(mode="json"),
        },
        "source": {
            "sha": reference.source_sha,
            "ci": reference.source_ci.model_dump(mode="json"),
            "reference_sha256": reference_digest,
            "artifact_sha256": artifact_digest,
            "artifact_schema": reference.artifact_schema,
            "protocol_sha256": reference.protocol_sha256,
        },
        "decision": reference.decision,
        "case_count": reference.case_count,
        "payload_granularity": "aggregate_only",
        "allowed_claims": list(reference.allowed_claims),
        "forbidden_claims": list(reference.forbidden_claims),
        "source_claim_boundary": boundary,
        "private_or_per_case_payload_present": False,
        "formal_case_result_status": "INPUT_REQUIRED",
        "formal_ab_status": "NOT_RUN_BY_EVALOPS",
        "formal_quality_claim_allowed": False,
        "production_ready": False,
    }


__all__ = ["AggregateContractPin", "ProducerAggregateReference", "verify_aggregate_contract"]
