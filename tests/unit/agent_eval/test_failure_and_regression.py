from app.agent_eval.failure_taxonomy import FailureCategory, classify_agent_failure
from app.agent_eval.regression import AgentComparisonCase, AgentRegressionGate, compare_agent_runs


def test_permission_leak_is_attributed_before_generic_terminal_failure() -> None:
    category = classify_agent_failure(
        {
            "unauthorized_result_leak_count": 1,
            "terminal_state": "agent_error",
        }
    )

    assert category is FailureCategory.PERMISSION_FAILURE


def test_agent_regression_gate_rejects_new_permission_violation() -> None:
    baseline = {
        "case-1": AgentComparisonCase(
            metrics={"task_success": True, "latency_ms": 100.0},
            terminal_state="answer",
            failure_category=None,
        )
    }
    candidate = {
        "case-1": AgentComparisonCase(
            metrics={"task_success": False, "latency_ms": 110.0},
            terminal_state="permission_denied",
            failure_category=FailureCategory.PERMISSION_FAILURE,
        )
    }

    report = compare_agent_runs(baseline, candidate)
    decision = AgentRegressionGate(
        task_success_min=0.9,
        permission_violation_max=0,
        latency_p95_max_regression_pct=20.0,
    ).assess(report)

    assert report.failure_category_distribution["permission_failure"]["right"] == 1
    assert decision.passed is False
    assert set(decision.violations) == {"task_success", "permission_violation"}
