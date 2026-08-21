import copy

import pytest

from app.agent_eval.schema import artifact_content_sha256
from app.external_harness.rag_harness import convert_rag_harness_result
from tests.unit.external_harness.rag_fixture import seal_rag_result


def test_rag_harness_result_converts_with_trace_and_source_identity() -> None:
    result = {
        "schema_name": "enterprise.agent-harness-result",
        "schema_version": "1.0",
        "case_id": "grounded-answer",
        "attempt_id": "attempt-001",
        "answer": "Manager approval is required.",
        "terminal_state": "answered",
        "citations": [{"document_id": "policy-7"}],
        "tool_events": [
            {
                "event_type": "tool.completed",
                "tool_name": "search",
                "sequence": 1,
                "payload": {"result_count": 1},
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
            "run_id": "run-001",
            "created_at": "2026-08-21T00:00:00Z",
            "session_id": "session-001",
            "git_sha": "e848d8e6090267b28d351758fe8d3cb557dcd586",
            "trace_context": {
                "trace_id": "1" * 32,
                "root_span_id": "2" * 16,
                "trace_schema_version": "enterprise.agent.telemetry/1.0",
                "content_capture_policy": "off",
                "sanitized_model_metadata": {},
                "sanitized_tool_metadata": {},
            },
            "trajectory": [
                {
                    "schema_version": "1.0",
                    "event_id": "event-001",
                    "session_id": "session-001",
                    "trace_id": "11111111111111111111111111111111",
                    "sequence": 1,
                    "event_type": "tool.completed",
                    "timestamp": "2026-08-21T00:00:01Z",
                    "tool_name": "search",
                    "payload": {"result_count": 1},
                }
            ],
            "retrieval": {},
            "evidence": {},
            "usage": {"step_count": 1},
            "terminal": {"state": "answered"},
        },
        "trace_id": "1" * 32,
        "root_span_id": "2" * 16,
        "propagated_traceparent": f"00-{'1' * 32}-{'2' * 16}-01",
        "error_classification": "ok",
    }

    result = seal_rag_result(result)

    first = convert_rag_harness_result(result)
    second = convert_rag_harness_result(result)

    assert first.framework == "enterprise-rag-agent-runtime"
    assert first.run_id == "run-001"
    assert first.terminal.state == "answer"
    assert first.metadata["producer_git_sha"] == result["trajectory_artifact"]["git_sha"]
    assert first.metadata["trace_id"] == "1" * 32
    assert first.trajectory[0].event_type == "tool_result"
    assert artifact_content_sha256(first) == artifact_content_sha256(second)


def test_rag_producer_digest_chain_order_duplicates_and_tool_surface_fail_closed() -> None:
    trace_id = "1" * 32
    base = {
        "schema_name": "enterprise.agent-harness-result",
        "schema_version": "1.0",
        "case_id": "integrity",
        "attempt_id": "attempt-integrity",
        "answer": "ok",
        "terminal_state": "answered",
        "citations": [],
        "tool_events": [],
        "policy_decisions": [],
        "trajectory_artifact": {
            "schema_name": "enterprise.agent-run",
            "schema_version": "1.0",
            "run_id": "run-integrity",
            "case_id": "integrity",
            "created_at": "2026-08-21T00:00:00Z",
            "session_id": "session-integrity",
            "git_sha": "e848d8e6090267b28d351758fe8d3cb557dcd586",
            "trace_id": trace_id,
            "trace_context": {
                "trace_id": trace_id,
                "root_span_id": "2" * 16,
                "trace_schema_version": "enterprise.agent.telemetry/1.0",
                "content_capture_policy": "off",
                "sanitized_model_metadata": {},
                "sanitized_tool_metadata": {},
            },
            "input": {},
            "output": {},
            "trajectory": [
                {
                    "schema_version": "1.0",
                    "event_id": "event-1",
                    "session_id": "session-integrity",
                    "trace_id": trace_id,
                    "sequence": 1,
                    "event_type": "session.completed",
                    "timestamp": "2026-08-21T00:00:01Z",
                    "payload": {},
                }
            ],
            "retrieval": {},
            "evidence": {},
            "usage": {},
            "terminal": {"mode": "answered"},
        },
        "trace_id": trace_id,
        "root_span_id": "2" * 16,
        "propagated_traceparent": f"00-{trace_id}-{'2' * 16}-01",
        "error_classification": "ok",
    }
    sealed = seal_rag_result(base)

    event_tamper = copy.deepcopy(sealed)
    event_tamper["trajectory_artifact"]["trajectory"][0]["payload"] = {"tampered": True}
    with pytest.raises(ValueError, match="event digest"):
        convert_rag_harness_result(event_tamper)

    artifact_tamper = copy.deepcopy(sealed)
    artifact_tamper["trajectory_artifact"]["output"] = {"tampered": True}
    with pytest.raises(ValueError, match="artifact digest"):
        convert_rag_harness_result(artifact_tamper)

    root_tamper = copy.deepcopy(sealed)
    root_tamper["trajectory_artifact"]["source_trajectory_root_hash"] = "f" * 64
    with pytest.raises(ValueError, match="root hash"):
        convert_rag_harness_result(root_tamper)

    duplicate = copy.deepcopy(base)
    duplicate_event = copy.deepcopy(duplicate["trajectory_artifact"]["trajectory"][0])
    duplicate_event["sequence"] = 2
    duplicate_event["timestamp"] = "2026-08-21T00:00:02Z"
    duplicate["trajectory_artifact"]["trajectory"].append(duplicate_event)
    with pytest.raises(ValueError, match="duplicate"):
        convert_rag_harness_result(seal_rag_result(duplicate))

    out_of_order = copy.deepcopy(base)
    second_event = copy.deepcopy(out_of_order["trajectory_artifact"]["trajectory"][0])
    second_event["event_id"] = "event-2"
    second_event["sequence"] = 3
    second_event["timestamp"] = "2026-08-21T00:00:02Z"
    out_of_order["trajectory_artifact"]["trajectory"].append(second_event)
    with pytest.raises(ValueError, match="sequence"):
        convert_rag_harness_result(seal_rag_result(out_of_order))

    tool_mismatch = copy.deepcopy(sealed)
    tool_mismatch["tool_events"] = [
        {
            "event_type": "tool.completed",
            "tool_name": "search",
            "sequence": 1,
            "payload": {},
        }
    ]
    with pytest.raises(ValueError, match="tool_events"):
        convert_rag_harness_result(tool_mismatch)
