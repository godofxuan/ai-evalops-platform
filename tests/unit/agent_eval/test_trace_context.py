from uuid import UUID

from app.agent_eval.trace_context import agent_eval_trace_attributes


def test_agent_trace_attributes_include_only_correlation_ids_and_framework() -> None:
    attributes = agent_eval_trace_attributes(
        session_id="session-001",
        framework="custom-controller",
        run_id=UUID("00000000-0000-0000-0000-000000000601"),
        job_id=UUID("00000000-0000-0000-0000-000000000602"),
        attempt_id=UUID("00000000-0000-0000-0000-000000000603"),
        case_id="case-001",
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
    )

    assert attributes == {
        "agent.session_id": "session-001",
        "agent.framework": "custom-controller",
        "eval.run_id": "00000000-0000-0000-0000-000000000601",
        "eval.job_id": "00000000-0000-0000-0000-000000000602",
        "eval.attempt_id": "00000000-0000-0000-0000-000000000603",
        "eval.case_id": "case-001",
        "tenant_id": "00000000-0000-0000-0000-000000000201",
    }
