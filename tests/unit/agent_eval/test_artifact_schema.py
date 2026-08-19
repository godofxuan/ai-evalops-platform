import math

import pytest

from app.agent_eval.schema import AgentRunArtifact, artifact_content_sha256


def test_framework_neutral_agent_run_artifact_has_stable_content_identity() -> None:
    artifact = AgentRunArtifact.model_validate(
        {
            "schema_version": "agent-run-artifact/v1",
            "run_id": "run-001",
            "case_id": "case-001",
            "session_id": "session-001",
            "framework": "custom-controller",
            "input": {"message": "Where is the handbook?"},
            "output": {"answer": "In the engineering drive."},
            "trajectory": [
                {
                    "event_id": "step-001",
                    "event_type": "user_message",
                    "payload": {"content": "Where is the handbook?"},
                },
                {
                    "event_id": "step-002",
                    "event_type": "tool_call",
                    "tool_name": "search_documents",
                    "payload": {"query": "engineering handbook"},
                },
                {
                    "event_id": "step-003",
                    "event_type": "terminal_state",
                    "payload": {"reason": "answer"},
                },
            ],
            "retrieval": {},
            "evidence": {},
            "usage": {},
            "terminal": {"state": "answer"},
            "metadata": {"adapter_version": "2026.08"},
        }
    )

    assert artifact.framework == "custom-controller"
    assert artifact.trajectory[1].tool_name == "search_documents"
    assert artifact_content_sha256(artifact) == artifact_content_sha256(
        AgentRunArtifact.model_validate_json(artifact.model_dump_json())
    )


def test_schema_accepts_runtime_labels_without_framework_specific_fields() -> None:
    payload = {
        "schema_version": "agent-run-artifact/v1",
        "run_id": "run-001",
        "case_id": "case-001",
        "session_id": "session-001",
        "framework": "langgraph-adapter",
        "input": {},
        "output": {},
        "trajectory": [],
        "terminal": {"state": "partial"},
    }

    assert AgentRunArtifact.model_validate(payload).framework == "langgraph-adapter"


@pytest.mark.parametrize(
    ("usage_key", "invalid_value"),
    [
        ("latency_ms", -1),
        ("cost", -0.01),
        ("input_tokens", -1),
        ("output_tokens", -1),
        ("latency_ms", math.nan),
        ("cost", math.inf),
    ],
)
def test_schema_rejects_invalid_nonnegative_finite_usage(
    usage_key: str, invalid_value: float
) -> None:
    payload = {
        "schema_version": "agent-run-artifact/v1",
        "run_id": "run-001",
        "case_id": "case-001",
        "session_id": "session-001",
        "framework": "custom-controller",
        "input": {},
        "output": {},
        "trajectory": [],
        "usage": {usage_key: invalid_value},
        "terminal": {"state": "answer"},
    }

    with pytest.raises(ValueError, match="non-negative finite"):
        AgentRunArtifact.model_validate(payload)


def test_schema_rejects_negative_trajectory_depth() -> None:
    payload = {
        "schema_version": "agent-run-artifact/v1",
        "run_id": "run-001",
        "case_id": "case-001",
        "session_id": "session-001",
        "framework": "custom-controller",
        "input": {},
        "output": {},
        "trajectory": [{"event_id": "1", "event_type": "tool_call", "payload": {"depth": -1}}],
        "terminal": {"state": "answer"},
    }

    with pytest.raises(ValueError, match="non-negative finite"):
        AgentRunArtifact.model_validate(payload)
