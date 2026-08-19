from app.agent_eval.evaluators import build_agent_evaluator, registered_agent_evaluators
from app.agent_eval.schema import AgentRunArtifact


def _artifact() -> AgentRunArtifact:
    return AgentRunArtifact.model_validate(
        {
            "schema_version": "agent-run-artifact/v1",
            "run_id": "run-001",
            "case_id": "case-001",
            "session_id": "session-001",
            "framework": "custom-controller",
            "input": {},
            "output": {"task_success": True},
            "trajectory": [
                {
                    "event_id": "call-1",
                    "event_type": "tool_call",
                    "tool_name": "search_documents",
                    "payload": {"authorized": True, "args_valid": True, "depth": 1},
                },
                {
                    "event_id": "call-2",
                    "event_type": "tool_call",
                    "tool_name": "delete_customer",
                    "payload": {"authorized": False, "args_valid": False, "depth": 2},
                },
                {
                    "event_id": "terminal-1",
                    "event_type": "terminal_state",
                    "payload": {"reason": "answer"},
                },
            ],
            "terminal": {"state": "answer"},
        }
    )


def test_tool_and_trajectory_evaluators_report_explainable_counts() -> None:
    artifact = _artifact()

    tool_metrics = build_agent_evaluator("tool_call_validity", {}).evaluate(artifact).metrics
    efficiency_metrics = (
        build_agent_evaluator("trajectory_efficiency", {}).evaluate(artifact).metrics
    )

    assert tool_metrics == {
        "tool_calls_total": 2,
        "tool_calls_valid": 1,
        "tool_calls_invalid": 1,
        "tool_calls_denied": 1,
        "tool_calls_error": 0,
    }
    assert efficiency_metrics["step_count"] == 3
    assert efficiency_metrics["tool_call_count"] == 2
    assert efficiency_metrics["max_depth"] == 2


def test_registry_exposes_only_deterministic_agent_evaluators() -> None:
    descriptors = {item.kind: item for item in registered_agent_evaluators()}

    assert set(descriptors) == {
        "task_success",
        "tool_call_validity",
        "trajectory_efficiency",
        "grounding_citation",
        "permission_boundary",
        "terminal_state",
        "cost_latency",
    }
    assert all(item.llm_judge is False for item in descriptors.values())
