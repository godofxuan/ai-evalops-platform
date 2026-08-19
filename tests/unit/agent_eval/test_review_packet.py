from app.agent_eval.review_packet import build_agent_review_packet
from app.agent_eval.schema import AgentRunArtifact


def test_agent_review_packet_hides_framework_and_limits_trajectory() -> None:
    artifact = AgentRunArtifact.model_validate(
        {
            "schema_version": "agent-run-artifact/v1",
            "run_id": "run-001",
            "case_id": "case-001",
            "session_id": "session-001",
            "framework": "langgraph-adapter",
            "input": {"message": "q"},
            "output": {"answer": "a"},
            "trajectory": [
                {"event_id": "1", "event_type": "model_step", "payload": {"internal": "hidden"}},
                {"event_id": "2", "event_type": "tool_call", "tool_name": "search", "payload": {}},
                {"event_id": "3", "event_type": "citation", "payload": {"id": "doc-1"}},
            ],
            "evidence": {"citations": ["doc-1"]},
            "terminal": {"state": "answer"},
        }
    )

    packet = build_agent_review_packet(artifact, evaluator_results={"task_success": True})

    assert packet["case_id"] == "case-001"
    assert "framework" not in packet
    assert "session_id" not in packet
    assert packet["trajectory"] == [
        {"event_type": "tool_call", "tool_name": "search"},
        {"event_type": "citation", "tool_name": None},
    ]
