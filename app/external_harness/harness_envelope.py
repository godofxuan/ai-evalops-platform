"""Versioned integrity envelope for the complete Enterprise RAG harness result."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.agent_eval.schema import AgentRunArtifact
from app.external_harness.rag_harness import (
    RagHarnessContractError,
    RagHarnessResultV1,
    convert_rag_harness_result,
)

RAG_REPOSITORY: Literal["https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot"] = (
    "https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot"
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class HarnessConversionMetadata(_StrictModel):
    canonical_json: Literal["RFC8259-sort-keys-compact-ensure-ascii"] = (
        "RFC8259-sort-keys-compact-ensure-ascii"
    )
    array_order: Literal["preserved"] = "preserved"
    number_policy: Literal["JSON-number-no-coercion"] = "JSON-number-no-coercion"
    policy_projection_source: Literal["producer-harness-policy-audit"] = (
        "producer-harness-policy-audit"
    )
    policy_projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RagHarnessEnvelopeV11(_StrictModel):
    schema_name: Literal["enterprise.agent-harness-envelope"] = "enterprise.agent-harness-envelope"
    schema_version: Literal["1.1"] = "1.1"
    producer_repository: Literal["https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot"]
    producer_source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    producer_contract_version: Literal["enterprise.agent-harness-result/1.0"]
    result: RagHarnessResultV1
    conversion_metadata: HarnessConversionMetadata
    harness_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def seal_rag_harness_result(
    result: object,
    *,
    producer_source_sha: str,
) -> dict[str, JsonValue]:
    """Verify producer integrity, then seal the complete result at the consumer boundary."""

    parsed = RagHarnessResultV1.model_validate(result)
    artifact = convert_rag_harness_result(parsed.model_dump(mode="json"))
    if artifact.metadata["producer_git_sha"] != producer_source_sha:
        raise RagHarnessContractError("producer source SHA differs from verified Artifact SHA")
    values: dict[str, object] = {
        "schema_name": "enterprise.agent-harness-envelope",
        "schema_version": "1.1",
        "producer_repository": RAG_REPOSITORY,
        "producer_source_sha": producer_source_sha,
        "producer_contract_version": "enterprise.agent-harness-result/1.0",
        "result": parsed.model_dump(mode="json"),
        "conversion_metadata": HarnessConversionMetadata(
            policy_projection_sha256=canonical_sha256(
                [decision.model_dump(mode="json") for decision in parsed.policy_decisions]
            )
        ).model_dump(mode="json"),
    }
    values["harness_result_sha256"] = canonical_sha256(values)
    return cast(dict[str, JsonValue], values)


def verify_and_convert_rag_envelope(envelope: object) -> AgentRunArtifact:
    """Fail closed on envelope/projection drift and return the verified EvalOps Artifact."""

    try:
        parsed = RagHarnessEnvelopeV11.model_validate(envelope)
    except ValueError as error:
        raise RagHarnessContractError(str(error)) from error
    expected = parsed.harness_result_sha256
    computed = canonical_sha256(parsed.model_dump(mode="json", exclude={"harness_result_sha256"}))
    if expected != computed:
        raise RagHarnessContractError(
            f"HARNESS_DIGEST_MISMATCH expected={expected} computed={computed}"
        )
    result = parsed.result
    producer = result.trajectory_artifact
    if producer.git_sha != parsed.producer_source_sha:
        raise RagHarnessContractError("PRODUCER_SHA_PROJECTION_MISMATCH")
    _verify_projections(result)
    _verify_policy_projection(result, parsed.conversion_metadata)
    artifact = convert_rag_harness_result(result.model_dump(mode="json"))
    metadata = dict(artifact.metadata)
    metadata.update(
        {
            "harness_envelope_schema": f"{parsed.schema_name}/{parsed.schema_version}",
            "harness_result_sha256": expected,
            "harness_result_sha256_expected": expected,
            "harness_result_sha256_computed": computed,
            "producer_repository": parsed.producer_repository,
            "producer_source_sha": parsed.producer_source_sha,
            "producer_contract_version": parsed.producer_contract_version,
            "integrity_verification": "verified",
        }
    )
    return artifact.model_copy(update={"metadata": metadata})


def _verify_projections(result: RagHarnessResultV1) -> None:
    producer = result.trajectory_artifact
    output = producer.output
    if output.get("answer") != result.answer:
        raise RagHarnessContractError("ANSWER_PROJECTION_MISMATCH")
    derived_citations = [
        event.payload for event in producer.trajectory if event.event_type == "citation.checked"
    ]
    if derived_citations != result.citations:
        raise RagHarnessContractError("CITATION_PROJECTION_MISMATCH")
    if producer.terminal.get("mode") != result.terminal_state:
        raise RagHarnessContractError("TERMINAL_PROJECTION_MISMATCH")
    expected_error = {
        "answered": "ok",
        "unsafe": "unsafe_request",
        "permission": "permission_denied",
        "not_found": "retrieval_miss",
        "security_filtered": "retrieved_content_blocked",
        "budget": "budget_exhausted",
        "system": "system_error",
        "partial": "partial_evidence",
    }.get(result.terminal_state, "unknown")
    if expected_error != result.error_classification:
        raise RagHarnessContractError("ERROR_PROJECTION_MISMATCH")
    derived_tools = [
        {
            "event_type": event.event_type,
            "tool_name": event.tool_name,
            "sequence": event.sequence,
            "payload": event.payload,
        }
        for event in producer.trajectory
        if event.event_type in {"tool.requested", "tool.completed", "tool.failed"}
    ]
    supplied_tools = [event.model_dump(mode="json") for event in result.tool_events]
    if supplied_tools != derived_tools:
        raise RagHarnessContractError("TOOL_PROJECTION_MISMATCH")


def _verify_policy_projection(
    result: RagHarnessResultV1,
    metadata: HarnessConversionMetadata,
) -> None:
    computed = canonical_sha256(
        [decision.model_dump(mode="json") for decision in result.policy_decisions]
    )
    if computed != metadata.policy_projection_sha256:
        raise RagHarnessContractError("POLICY_PROJECTION_MISMATCH")


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "HarnessConversionMetadata",
    "RAG_REPOSITORY",
    "RagHarnessEnvelopeV11",
    "canonical_sha256",
    "seal_rag_harness_result",
    "verify_and_convert_rag_envelope",
]
