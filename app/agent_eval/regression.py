"""Run-to-run comparison and explicitly configured Agent regression decisions."""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.agent_eval.failure_taxonomy import FailureCategory


@dataclass(frozen=True, slots=True)
class AgentComparisonCase:
    metrics: dict[str, Any]
    terminal_state: str
    failure_category: FailureCategory | None


@dataclass(frozen=True, slots=True)
class AgentRegressionReport:
    intersection_count: int
    left_only_count: int
    right_only_count: int
    task_success_rate: dict[str, float | None]
    latency_p95_ms: dict[str, float | None]
    terminal_distribution: dict[str, dict[str, int]]
    failure_category_distribution: dict[str, dict[str, int]]


@dataclass(frozen=True, slots=True)
class AgentRegressionDecision:
    passed: bool
    violations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AgentRegressionGate:
    """Project-configured thresholds, deliberately not universal quality claims."""

    task_success_min: float | None = None
    permission_violation_max: int | None = None
    latency_p95_max_regression_pct: float | None = None
    tool_error_rate_max: float | None = None

    def assess(self, report: AgentRegressionReport) -> AgentRegressionDecision:
        violations: list[str] = []
        candidate_success = report.task_success_rate["right"]
        if self.task_success_min is not None and (
            candidate_success is None or candidate_success < self.task_success_min
        ):
            violations.append("task_success")
        permission_count = report.failure_category_distribution.get(
            FailureCategory.PERMISSION_FAILURE.value, {"right": 0}
        )["right"]
        if (
            self.permission_violation_max is not None
            and permission_count > self.permission_violation_max
        ):
            violations.append("permission_violation")
        baseline_p95 = report.latency_p95_ms["left"]
        candidate_p95 = report.latency_p95_ms["right"]
        if (
            self.latency_p95_max_regression_pct is not None
            and baseline_p95 is not None
            and baseline_p95 > 0
            and candidate_p95 is not None
            and ((candidate_p95 - baseline_p95) / baseline_p95 * 100)
            > self.latency_p95_max_regression_pct
        ):
            violations.append("latency_p95")
        tool_errors = report.failure_category_distribution.get(
            FailureCategory.TOOL_FAILURE.value, {"right": 0}
        )["right"]
        if (
            self.tool_error_rate_max is not None
            and report.intersection_count > 0
            and tool_errors / report.intersection_count > self.tool_error_rate_max
        ):
            violations.append("tool_error_rate")
        return AgentRegressionDecision(passed=not violations, violations=tuple(violations))


def compare_agent_runs(
    left: dict[str, AgentComparisonCase],
    right: dict[str, AgentComparisonCase],
) -> AgentRegressionReport:
    left_ids = set(left)
    right_ids = set(right)
    terminal = _two_sided_distribution(left, right, lambda item: item.terminal_state)
    failures = _two_sided_distribution(
        left,
        right,
        lambda item: None if item.failure_category is None else item.failure_category.value,
    )
    return AgentRegressionReport(
        intersection_count=len(left_ids & right_ids),
        left_only_count=len(left_ids - right_ids),
        right_only_count=len(right_ids - left_ids),
        task_success_rate={"left": _success_rate(left), "right": _success_rate(right)},
        latency_p95_ms={"left": _p95(left), "right": _p95(right)},
        terminal_distribution=terminal,
        failure_category_distribution=failures,
    )


def _two_sided_distribution(
    left: dict[str, AgentComparisonCase],
    right: dict[str, AgentComparisonCase],
    key: Callable[[AgentComparisonCase], str | None],
) -> dict[str, dict[str, int]]:
    left_counts = Counter(key(item) for item in left.values())
    right_counts = Counter(key(item) for item in right.values())
    return {
        str(name): {"left": left_counts[name], "right": right_counts[name]}
        for name in sorted(set(left_counts) | set(right_counts), key=lambda value: str(value))
        if name is not None
    }


def _success_rate(cases: dict[str, AgentComparisonCase]) -> float | None:
    values = [item.metrics.get("task_success") for item in cases.values()]
    known = [item for item in values if isinstance(item, bool)]
    return None if not known else sum(known) / len(known)


def _p95(cases: dict[str, AgentComparisonCase]) -> float | None:
    values = sorted(
        float(value)
        for item in cases.values()
        if isinstance((value := item.metrics.get("latency_ms")), (int, float))
        and not isinstance(value, bool)
    )
    if not values:
        return None
    position = (len(values) - 1) * 0.95
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)
