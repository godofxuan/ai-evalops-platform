import pytest

from app.external_harness.rag_harness import (
    RagHarnessContractError,
    convert_rag_harness_result,
)


def test_real_producer_fields_are_validated_and_preserved() -> None:
    trace_id = "1" * 32
    span_id = "2" * 16
    result = {
        "schema_name": "enterprise.agent-harness-result",
        "schema_version": "1.0",
        "case_id": "real-cli-smoke",
        "attempt_id": "evalops-attempt-001",
        "answer": "Remote policy allows three days per month.",
        "terminal_state": "answered",
        "citations": [],
        "tool_events": [],
        "policy_decisions": [],
        "trajectory_artifact": {
            "schema_name": "enterprise.agent-run",
            "schema_version": "1.0",
            "run_id": "run-001",
            "case_id": "real-cli-smoke",
            "git_sha": "e848d8e6090267b28d351758fe8d3cb557dcd586",
            "created_at": "2026-08-21T00:00:00Z",
            "session_id": "session-001",
            "trace_id": trace_id,
            "trace_context": {
                "trace_id": trace_id,
                "root_span_id": span_id,
                "trace_schema_version": "enterprise.agent.telemetry/1.0",
                "content_capture_policy": "off",
                "sanitized_model_metadata": {},
                "sanitized_tool_metadata": {"runtime": "deterministic_mock"},
            },
            "input": {"question": "What is the remote policy?"},
            "output": {"mode": "answered"},
            "trajectory": [],
            "retrieval": {},
            "evidence": {},
            "usage": {},
            "terminal": {"mode": "answered"},
            "source_trajectory_root_hash": "b" * 64,
            "artifact_sha256": "c" * 64,
        },
        "trace_id": trace_id,
        "root_span_id": span_id,
        "propagated_traceparent": f"00-{trace_id}-{span_id}-01",
        "error_classification": "ok",
    }

    artifact = convert_rag_harness_result(result)

    assert artifact.input == result["trajectory_artifact"]["input"]
    assert artifact.metadata["producer_artifact_sha256"] == "c" * 64

    result["trajectory_artifact"]["case_id"] = "different-case"
    with pytest.raises(RagHarnessContractError, match="case"):
        convert_rag_harness_result(result)
