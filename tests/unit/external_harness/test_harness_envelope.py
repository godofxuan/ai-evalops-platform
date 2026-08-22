import json
from collections.abc import Callable
from typing import Any

import pytest

from app.external_harness.harness_envelope import (
    canonical_sha256,
    seal_rag_harness_result,
    verify_and_convert_rag_envelope,
)
from app.external_harness.rag_harness import RagHarnessContractError
from tests.unit.external_harness.rag_fixture import seal_rag_result

PRODUCER_SHA = "d" * 40


def _raw_result() -> dict[str, Any]:
    trace_id = "1" * 32
    result = {
        "schema_name": "enterprise.agent-harness-result",
        "schema_version": "1.0",
        "case_id": "envelope-case",
        "attempt_id": "attempt-1",
        "answer": "Grounded answer",
        "terminal_state": "answered",
        "citations": [
            {"document_id": "doc-1", "source": "policy"},
            {"document_id": "doc-2", "source": "handbook"},
        ],
        "tool_events": [
            {
                "event_type": "tool.completed",
                "tool_name": "search",
                "sequence": 1,
                "payload": {"arguments": {"query": "policy"}, "result": {"count": 1}},
            }
        ],
        "policy_decisions": [
            {
                "lifecycle": "before",
                "tool_name": "search",
                "decision": "ALLOW",
                "reason_code": "policy_allow",
                "arguments_sha256": "a" * 64,
            }
        ],
        "trajectory_artifact": {
            "schema_name": "enterprise.agent-run",
            "schema_version": "1.0",
            "run_id": "run-envelope",
            "case_id": "envelope-case",
            "created_at": "2026-08-22T00:00:02Z",
            "session_id": "session-envelope",
            "git_sha": PRODUCER_SHA,
            "trace_id": trace_id,
            "trace_context": {
                "trace_id": trace_id,
                "root_span_id": "2" * 16,
                "trace_schema_version": "enterprise.agent.telemetry/1.0",
                "content_capture_policy": "off",
                "sanitized_model_metadata": {},
                "sanitized_tool_metadata": {},
            },
            "input": {"question": "policy?"},
            "output": {
                "answer": "Grounded answer",
                "citations": [
                    {"document_id": "doc-1", "source": "policy"},
                    {"document_id": "doc-2", "source": "handbook"},
                ],
                "mode": "answered",
            },
            "trajectory": [
                {
                    "schema_version": "1.0",
                    "event_id": "event-1",
                    "session_id": "session-envelope",
                    "trace_id": trace_id,
                    "sequence": 1,
                    "event_type": "tool.completed",
                    "timestamp": "2026-08-22T00:00:01Z",
                    "tool_name": "search",
                    "payload": {"arguments": {"query": "policy"}, "result": {"count": 1}},
                },
                {
                    "schema_version": "1.0",
                    "event_id": "citation-1",
                    "session_id": "session-envelope",
                    "trace_id": trace_id,
                    "sequence": 2,
                    "event_type": "citation.checked",
                    "timestamp": "2026-08-22T00:00:01Z",
                    "payload": {"document_id": "doc-1", "source": "policy"},
                },
                {
                    "schema_version": "1.0",
                    "event_id": "citation-2",
                    "session_id": "session-envelope",
                    "trace_id": trace_id,
                    "sequence": 3,
                    "event_type": "citation.checked",
                    "timestamp": "2026-08-22T00:00:01Z",
                    "payload": {"document_id": "doc-2", "source": "handbook"},
                },
                {
                    "schema_version": "1.0",
                    "event_id": "event-2",
                    "session_id": "session-envelope",
                    "trace_id": trace_id,
                    "sequence": 4,
                    "event_type": "session.completed",
                    "timestamp": "2026-08-22T00:00:02Z",
                    "payload": {"mode": "answered"},
                },
            ],
            "retrieval": {},
            "evidence": {},
            "usage": {},
            "terminal": {"mode": "answered", "completed": True},
        },
        "trace_id": trace_id,
        "root_span_id": "2" * 16,
        "propagated_traceparent": f"00-{trace_id}-{'2' * 16}-01",
        "error_classification": "ok",
        "durability_scope": "access_request_draft_only",
        "start_idempotency_supported": True,
        "resume_concurrency_fenced": True,
        "multi_instance_ha": False,
    }
    return seal_rag_result(result)


def _envelope() -> dict[str, Any]:
    return seal_rag_harness_result(_raw_result(), producer_source_sha=PRODUCER_SHA)


def _reseal(envelope: dict[str, Any]) -> None:
    envelope["harness_result_sha256"] = canonical_sha256(
        {key: value for key, value in envelope.items() if key != "harness_result_sha256"}
    )


def test_complete_envelope_digest_is_deterministic_and_preserved() -> None:
    first = _envelope()
    second = json.loads(json.dumps(first, sort_keys=False))
    reversed_order = dict(reversed(list(second.items())))

    artifact = verify_and_convert_rag_envelope(reversed_order)

    assert first["harness_result_sha256"] == second["harness_result_sha256"]
    assert artifact.metadata["harness_result_sha256"] == first["harness_result_sha256"]
    assert (
        artifact.metadata["harness_result_sha256_expected"]
        == artifact.metadata["harness_result_sha256_computed"]
    )
    assert artifact.metadata["producer_source_sha"] == PRODUCER_SHA


Mutation = Callable[[dict[str, Any]], None]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["result"].__setitem__("answer", "tampered"),
        lambda value: value["result"]["citations"][0].__setitem__("document_id", "other"),
        lambda value: value["result"]["citations"][0].__setitem__("source", "other"),
        lambda value: value["result"]["citations"].reverse(),
        lambda value: value["result"].__setitem__("terminal_state", "partial"),
        lambda value: value["result"]["policy_decisions"][0].__setitem__("decision", "DENY"),
        lambda value: value["result"]["policy_decisions"][0].__setitem__("reason_code", "risk"),
        lambda value: value["result"].__setitem__("error_classification", "system_error"),
        lambda value: value["result"]["tool_events"][0]["payload"]["arguments"].__setitem__(
            "query", "tampered"
        ),
        lambda value: value["result"]["tool_events"][0]["payload"]["result"].__setitem__(
            "count", 99
        ),
        lambda value: value["result"].__setitem__("trace_id", "3" * 32),
        lambda value: value["result"].__setitem__("case_id", "other-case"),
        lambda value: value.__setitem__("producer_source_sha", "e" * 40),
        lambda value: value.__setitem__("schema_version", "1.0"),
        lambda value: value.__setitem__("harness_result_sha256", "f" * 64),
        lambda value: value["result"]["trajectory_artifact"].__setitem__(
            "artifact_sha256", "f" * 64
        ),
        lambda value: value["result"]["trajectory_artifact"].__setitem__(
            "source_trajectory_root_hash", "f" * 64
        ),
        lambda value: value["result"]["trajectory_artifact"]["trajectory"].reverse(),
    ],
)
def test_single_field_tampering_fails_closed(mutate: Mutation) -> None:
    envelope = _envelope()
    mutate(envelope)
    with pytest.raises(RagHarnessContractError):
        verify_and_convert_rag_envelope(envelope)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value["result"].__setitem__("answer", "tampered"), "ANSWER"),
        (
            lambda value: value["result"].__setitem__(
                "citations", [{"document_id": "other", "source": "policy"}]
            ),
            "CITATION",
        ),
        (lambda value: value["result"].__setitem__("terminal_state", "partial"), "TERMINAL"),
        (
            lambda value: value["result"].__setitem__("error_classification", "system_error"),
            "ERROR",
        ),
        (
            lambda value: value["result"]["policy_decisions"][0].__setitem__(
                "reason_code", "tampered-risk"
            ),
            "POLICY_PROJECTION_MISMATCH",
        ),
        (
            lambda value: value["result"]["tool_events"][0]["payload"]["arguments"].__setitem__(
                "query", "tampered"
            ),
            "TOOL_PROJECTION_MISMATCH",
        ),
    ],
)
def test_projection_mismatch_rejected_even_with_recomputed_envelope_digest(
    mutate: Mutation,
    message: str,
) -> None:
    envelope = _envelope()
    mutate(envelope)
    _reseal(envelope)
    with pytest.raises(RagHarnessContractError, match=message):
        verify_and_convert_rag_envelope(envelope)


def test_unknown_or_missing_envelope_fields_fail_closed() -> None:
    additional = _envelope()
    additional["unknown"] = True
    missing = _envelope()
    del missing["producer_contract_version"]

    with pytest.raises(RagHarnessContractError):
        verify_and_convert_rag_envelope(additional)
    with pytest.raises(RagHarnessContractError):
        verify_and_convert_rag_envelope(missing)


def test_canonical_json_preserves_array_order_and_unicode_code_points() -> None:
    assert canonical_sha256({"values": [1, 2]}) != canonical_sha256({"values": [2, 1]})
    assert canonical_sha256({"text": "é"}) != canonical_sha256({"text": "e\u0301"})
    assert canonical_sha256({"text": "评测"}) == canonical_sha256({"text": "\u8bc4\u6d4b"})


def test_canonical_json_distinguishes_integer_and_float_and_rejects_nan() -> None:
    assert canonical_sha256({"value": 1}) != canonical_sha256({"value": 1.0})
    with pytest.raises(ValueError, match="JSON compliant"):
        canonical_sha256({"value": float("nan")})


def test_duplicate_tool_and_unknown_producer_event_fail_closed() -> None:
    duplicate_tool = _envelope()
    duplicate_tool["result"]["tool_events"].append(duplicate_tool["result"]["tool_events"][0])
    _reseal(duplicate_tool)

    unknown_event = _envelope()
    unknown_event["result"]["trajectory_artifact"]["trajectory"][0]["event_type"] = "tool.unknown"
    _reseal(unknown_event)

    with pytest.raises(RagHarnessContractError, match="TOOL_PROJECTION_MISMATCH"):
        verify_and_convert_rag_envelope(duplicate_tool)
    with pytest.raises(RagHarnessContractError):
        verify_and_convert_rag_envelope(unknown_event)
