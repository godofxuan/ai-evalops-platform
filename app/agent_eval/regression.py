"""Run-to-run comparison over an explicit common-case evidence contract."""

import hashlib
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from app.agent_eval.failure_taxonomy import FailureCategory

CaseSetPolicy = Literal["exact", "intersection", "allow-diff"]
MissingMetricPolicy = Literal["fail", "warn", "ignore"]


@dataclass(frozen=True, slots=True)
class AgentComparisonCase:
    metrics: dict[str, Any]
    terminal_state: str
    failure_category: FailureCategory | None
    metric_trust: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MetricEvidence:
    sample_count: dict[str, int]
    coverage: dict[str, float]
    missing_count: dict[str, int]


@dataclass(frozen=True, slots=True)
class RunDiagnostics:
    case_count: int
    case_ids_sha256: str
    task_success_rate: float | None
    latency_p95_ms: float | None
    terminal_distribution: dict[str, int]
    failure_category_distribution: dict[str, int]


@dataclass(frozen=True, slots=True)
class AgentRegressionReport:
    case_set_policy: CaseSetPolicy
    common_case_ids: tuple[str, ...]
    common_case_ids_sha256: str
    intersection_count: int
    left_only_case_ids: tuple[str, ...]
    right_only_case_ids: tuple[str, ...]
    left_only_count: int
    right_only_count: int
    task_success_rate: dict[str, float | None]
    latency_p95_ms: dict[str, float | None]
    permission_violation_count: dict[str, int]
    tool_error_rate: dict[str, float | None]
    terminal_distribution: dict[str, dict[str, int]]
    failure_category_distribution: dict[str, dict[str, int]]
    metric_evidence: dict[str, MetricEvidence]
    metric_trust: dict[str, dict[str, dict[str, int]]]
    left_full_run_diagnostics: RunDiagnostics
    right_full_run_diagnostics: RunDiagnostics


@dataclass(frozen=True, slots=True)
class AgentRegressionDecision:
    passed: bool
    gate_executed: bool
    evidence_sufficient: bool
    status: Literal["passed", "failed", "insufficient_evidence", "case_set_mismatch"]
    violations: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AgentRegressionGate:
    """Caller thresholds plus explicit fail-closed evidence requirements."""

    task_success_min: float | None = None
    permission_violation_max: int | None = None
    latency_p95_max_regression_pct: float | None = None
    tool_error_rate_max: float | None = None
    minimum_intersection_count: int = 1
    minimum_metric_sample_count: int = 2
    minimum_metric_coverage: float = 1.0
    missing_metric_policy: MissingMetricPolicy = "fail"
    case_set_policy: CaseSetPolicy = "exact"
    allow_reported_evidence: bool = False

    def assess(self, report: AgentRegressionReport) -> AgentRegressionDecision:
        if self.case_set_policy != report.case_set_policy:
            raise ValueError("gate and report case_set_policy must match")
        if self.case_set_policy == "exact" and (report.left_only_count or report.right_only_count):
            return _blocked("case_set_mismatch", ("case_set_mismatch",))

        insufficiencies: list[str] = []
        if report.intersection_count < self.minimum_intersection_count:
            insufficiencies.append("minimum_intersection_count")
        required: list[tuple[str, tuple[str, ...]]] = []
        if self.task_success_min is not None:
            required.append(("task_success", ("right",)))
            if (
                not self.allow_reported_evidence
                and report.metric_trust["task_success"]["right"].get("reported", 0) > 0
            ):
                insufficiencies.append("task_success.reported_evidence")
        if self.latency_p95_max_regression_pct is not None:
            required.append(("latency_ms", ("left", "right")))
        if self.permission_violation_max is not None:
            required.append(("unauthorized_result_leak_count", ("right",)))
        for metric_name, sides in required:
            evidence = report.metric_evidence[metric_name]
            for side in sides:
                if evidence.sample_count[side] < self.minimum_metric_sample_count:
                    insufficiencies.append(f"{metric_name}.{side}.sample_count")
                if evidence.coverage[side] < self.minimum_metric_coverage:
                    insufficiencies.append(f"{metric_name}.{side}.coverage")
        warnings = tuple(dict.fromkeys(insufficiencies))
        if insufficiencies and self.missing_metric_policy == "fail":
            return _blocked("insufficient_evidence", warnings)

        violations: list[str] = []
        candidate_success = report.task_success_rate["right"]
        if self.task_success_min is not None and (
            candidate_success is None or candidate_success < self.task_success_min
        ):
            violations.append("task_success")
        if (
            self.permission_violation_max is not None
            and report.permission_violation_count["right"] > self.permission_violation_max
        ):
            violations.append("permission_violation")
        baseline_p95 = report.latency_p95_ms["left"]
        candidate_p95 = report.latency_p95_ms["right"]
        if (
            self.latency_p95_max_regression_pct is not None
            and baseline_p95 is not None
            and baseline_p95 > 0
            and candidate_p95 is not None
            and (candidate_p95 - baseline_p95) / baseline_p95 * 100
            > self.latency_p95_max_regression_pct
        ):
            violations.append("latency_p95")
        candidate_tool_rate = report.tool_error_rate["right"]
        if self.tool_error_rate_max is not None and (
            candidate_tool_rate is None or candidate_tool_rate > self.tool_error_rate_max
        ):
            violations.append("tool_error_rate")
        return AgentRegressionDecision(
            passed=not violations,
            gate_executed=True,
            evidence_sufficient=not insufficiencies,
            status="failed" if violations else "passed",
            violations=tuple(violations),
            warnings=warnings if self.missing_metric_policy == "warn" else (),
        )


def _blocked(
    status: Literal["insufficient_evidence", "case_set_mismatch"],
    warnings: tuple[str, ...],
) -> AgentRegressionDecision:
    return AgentRegressionDecision(
        passed=False,
        gate_executed=False,
        evidence_sufficient=False,
        status=status,
        violations=(status,),
        warnings=warnings,
    )


def compare_agent_runs(
    left: dict[str, AgentComparisonCase],
    right: dict[str, AgentComparisonCase],
    *,
    case_set_policy: CaseSetPolicy = "exact",
) -> AgentRegressionReport:
    left_ids = set(left)
    right_ids = set(right)
    common_ids = tuple(sorted(left_ids & right_ids))
    common_left = {case_id: left[case_id] for case_id in common_ids}
    common_right = {case_id: right[case_id] for case_id in common_ids}
    failures = _two_sided_distribution(
        common_left,
        common_right,
        lambda item: None if item.failure_category is None else item.failure_category.value,
    )
    tool_errors = failures.get(FailureCategory.TOOL_FAILURE.value, {"left": 0, "right": 0})
    count = len(common_ids)
    return AgentRegressionReport(
        case_set_policy=case_set_policy,
        common_case_ids=common_ids,
        common_case_ids_sha256=_case_ids_sha256(common_ids),
        intersection_count=count,
        left_only_case_ids=tuple(sorted(left_ids - right_ids)),
        right_only_case_ids=tuple(sorted(right_ids - left_ids)),
        left_only_count=len(left_ids - right_ids),
        right_only_count=len(right_ids - left_ids),
        task_success_rate={
            "left": _success_rate(common_left),
            "right": _success_rate(common_right),
        },
        latency_p95_ms={"left": _p95(common_left), "right": _p95(common_right)},
        permission_violation_count={
            "left": _metric_count(common_left, "unauthorized_result_leak_count"),
            "right": _metric_count(common_right, "unauthorized_result_leak_count"),
        },
        tool_error_rate={
            side: None if count == 0 else tool_errors[side] / count for side in ("left", "right")
        },
        terminal_distribution=_two_sided_distribution(
            common_left, common_right, lambda item: item.terminal_state
        ),
        failure_category_distribution=failures,
        metric_evidence={
            name: _metric_evidence(common_left, common_right, name)
            for name in ("task_success", "latency_ms", "unauthorized_result_leak_count")
        },
        metric_trust={
            name: {
                "left": _trust_counts(common_left, name),
                "right": _trust_counts(common_right, name),
            }
            for name in ("task_success", "latency_ms", "unauthorized_result_leak_count")
        },
        left_full_run_diagnostics=_run_diagnostics(left),
        right_full_run_diagnostics=_run_diagnostics(right),
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
    known = [
        value
        for item in cases.values()
        if isinstance((value := item.metrics.get("task_success")), bool)
    ]
    return None if not known else sum(known) / len(known)


def _p95(cases: dict[str, AgentComparisonCase]) -> float | None:
    values = sorted(
        number
        for item in cases.values()
        if (number := _finite_number(item.metrics.get("latency_ms"))) is not None
    )
    if not values:
        return None
    position = (len(values) - 1) * 0.95
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _metric_count(cases: dict[str, AgentComparisonCase], metric_name: str) -> int:
    total = 0
    for item in cases.values():
        number = _finite_number(item.metrics.get(metric_name))
        if number is not None and number > 0:
            total += int(number)
    return total


def _metric_evidence(
    left: dict[str, AgentComparisonCase],
    right: dict[str, AgentComparisonCase],
    metric_name: str,
) -> MetricEvidence:
    total = len(left)
    counts = {
        side: sum(
            1
            for item in cases.values()
            if _is_metric_sample(metric_name, item.metrics.get(metric_name))
        )
        for side, cases in (("left", left), ("right", right))
    }
    return MetricEvidence(
        sample_count=counts,
        coverage={side: 0.0 if total == 0 else value / total for side, value in counts.items()},
        missing_count={side: total - value for side, value in counts.items()},
    )


def _is_metric_sample(metric_name: str, value: object) -> bool:
    return isinstance(value, bool) if metric_name == "task_success" else _is_finite_number(value)


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float("-inf") < float(value) < float("inf")
    )


def _finite_number(value: object) -> float | None:
    if not _is_finite_number(value):
        return None
    assert isinstance(value, (int, float)) and not isinstance(value, bool)
    return float(value)


def _case_ids_sha256(case_ids: tuple[str, ...]) -> str:
    encoded = json.dumps(case_ids, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _one_sided_distribution(
    cases: dict[str, AgentComparisonCase],
    key: Callable[[AgentComparisonCase], str | None],
) -> dict[str, int]:
    counts = Counter(key(item) for item in cases.values())
    return {
        str(name): counts[name]
        for name in sorted(counts, key=lambda value: str(value))
        if name is not None
    }


def _run_diagnostics(cases: dict[str, AgentComparisonCase]) -> RunDiagnostics:
    return RunDiagnostics(
        case_count=len(cases),
        case_ids_sha256=_case_ids_sha256(tuple(sorted(cases))),
        task_success_rate=_success_rate(cases),
        latency_p95_ms=_p95(cases),
        terminal_distribution=_one_sided_distribution(cases, lambda item: item.terminal_state),
        failure_category_distribution=_one_sided_distribution(
            cases,
            lambda item: None if item.failure_category is None else item.failure_category.value,
        ),
    )


def _trust_counts(cases: dict[str, AgentComparisonCase], metric_name: str) -> dict[str, int]:
    counts = Counter(
        item.metric_trust.get(metric_name, "unknown")
        for item in cases.values()
        if metric_name in item.metrics
    )
    return dict(sorted(counts.items()))
