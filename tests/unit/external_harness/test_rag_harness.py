from app.agent_eval.schema import artifact_content_sha256
from app.external_harness.rag_harness import convert_rag_harness_result


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
                "sequence": 3,
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
            "trajectory": [],
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

    first = convert_rag_harness_result(result)
    second = convert_rag_harness_result(result)

    assert first.framework == "enterprise-rag-agent-runtime"
    assert first.run_id == "run-001"
    assert first.terminal.state == "answer"
    assert first.metadata["producer_git_sha"] == result["trajectory_artifact"]["git_sha"]
    assert first.metadata["trace_id"] == "1" * 32
    assert first.trajectory[0].event_type == "tool_result"
    assert artifact_content_sha256(first) == artifact_content_sha256(second)
