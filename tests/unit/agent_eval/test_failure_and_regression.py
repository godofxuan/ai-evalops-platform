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
            metrics={
                "task_success": False,
                "latency_ms": 110.0,
                "unauthorized_result_leak_count": 1,
            },
            terminal_state="permission_denied",
            failure_category=FailureCategory.PERMISSION_FAILURE,
        )
    }

    report = compare_agent_runs(baseline, candidate)
    decision = AgentRegressionGate(
        task_success_min=0.9,
        permission_violation_max=0,
        latency_p95_max_regression_pct=20.0,
        minimum_metric_sample_count=1,
    ).assess(report)

    assert report.failure_category_distribution["permission_failure"]["right"] == 1
    assert decision.passed is False
    assert set(decision.violations) == {"task_success", "permission_violation"}


def test_expected_permission_denial_is_not_counted_as_a_boundary_violation() -> None:
    denied_without_leak = {
        "case-1": AgentComparisonCase(
            metrics={
                "task_success": True,
                "unauthorized_result_leak_count": 0,
            },
            terminal_state="permission_denied",
            failure_category=FailureCategory.PERMISSION_FAILURE,
        )
    }

    report = compare_agent_runs(denied_without_leak, denied_without_leak)
    decision = AgentRegressionGate(
        permission_violation_max=0,
        minimum_metric_sample_count=1,
    ).assess(report)

    assert decision.passed is True


def test_regression_metrics_use_only_common_cases() -> None:
    baseline = {
        "A": AgentComparisonCase(
            metrics={"task_success": True, "latency_ms": 100.0},
            terminal_state="answer",
            failure_category=None,
        ),
        "B": AgentComparisonCase(
            metrics={"task_success": False, "latency_ms": 10_000.0},
            terminal_state="agent_error",
            failure_category=FailureCategory.TOOL_FAILURE,
        ),
    }
    candidate = {
        "A": AgentComparisonCase(
            metrics={"task_success": True, "latency_ms": 100.0},
            terminal_state="answer",
            failure_category=None,
        ),
        "C": AgentComparisonCase(
            metrics={
                "task_success": False,
                "latency_ms": 20_000.0,
                "unauthorized_result_leak_count": 1,
            },
            terminal_state="permission_denied",
            failure_category=FailureCategory.PERMISSION_FAILURE,
        ),
    }

    report = compare_agent_runs(baseline, candidate)

    assert report.intersection_count == 1
    assert report.left_only_count == 1
    assert report.right_only_count == 1
    assert report.task_success_rate == {"left": 1.0, "right": 1.0}
    assert report.latency_p95_ms == {"left": 100.0, "right": 100.0}
    assert report.permission_violation_count == {"left": 0, "right": 0}
    assert report.failure_category_distribution == {}


def test_zero_intersection_fails_closed() -> None:
    left = {
        "A": AgentComparisonCase(
            metrics={"task_success": True}, terminal_state="answer", failure_category=None
        )
    }
    right = {
        "B": AgentComparisonCase(
            metrics={"task_success": True}, terminal_state="answer", failure_category=None
        )
    }

    decision = AgentRegressionGate(case_set_policy="intersection").assess(
        compare_agent_runs(left, right, case_set_policy="intersection")
    )

    assert decision.status == "insufficient_evidence"
    assert decision.gate_executed is False
    assert decision.passed is False


def test_exact_policy_rejects_different_case_sets_without_running_gate() -> None:
    common = AgentComparisonCase(
        metrics={"task_success": True}, terminal_state="answer", failure_category=None
    )
    report = compare_agent_runs({"A": common, "B": common}, {"A": common})

    decision = AgentRegressionGate().assess(report)

    assert decision.status == "case_set_mismatch"
    assert decision.gate_executed is False


def test_single_latency_sample_is_insufficient_by_safe_default() -> None:
    baseline = AgentComparisonCase(
        metrics={"latency_ms": 100.0}, terminal_state="answer", failure_category=None
    )
    candidate = AgentComparisonCase(
        metrics={"latency_ms": 110.0}, terminal_state="answer", failure_category=None
    )

    decision = AgentRegressionGate(latency_p95_max_regression_pct=20.0).assess(
        compare_agent_runs({"A": baseline}, {"A": candidate})
    )

    assert decision.status == "insufficient_evidence"
    assert "latency_ms.left.sample_count" in decision.warnings


def test_right_only_tool_error_does_not_change_common_case_rate() -> None:
    common = AgentComparisonCase(
        metrics={"task_success": True}, terminal_state="answer", failure_category=None
    )
    tool_error = AgentComparisonCase(
        metrics={"task_success": False},
        terminal_state="agent_error",
        failure_category=FailureCategory.TOOL_FAILURE,
    )

    report = compare_agent_runs(
        {"A": common},
        {"A": common, "C": tool_error},
        case_set_policy="intersection",
    )

    assert report.tool_error_rate == {"left": 0.0, "right": 0.0}
    assert report.right_full_run_diagnostics.failure_category_distribution == {"tool_failure": 1}


def test_reported_task_success_requires_explicit_gate_opt_in() -> None:
    reported = AgentComparisonCase(
        metrics={"task_success": True},
        terminal_state="answer",
        failure_category=None,
        metric_trust={"task_success": "reported"},
    )
    report = compare_agent_runs({"A": reported}, {"A": reported})

    blocked = AgentRegressionGate(
        task_success_min=1.0,
        minimum_metric_sample_count=1,
    ).assess(report)
    allowed = AgentRegressionGate(
        task_success_min=1.0,
        minimum_metric_sample_count=1,
        allow_reported_evidence=True,
    ).assess(report)

    assert blocked.status == "insufficient_evidence"
    assert "task_success.reported_evidence" in blocked.warnings
    assert allowed.status == "passed"
