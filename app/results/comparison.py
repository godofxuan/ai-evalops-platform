from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.domain.enums import JobStatus
from app.results.metrics import CaseOutcome, MetricsSummary, aggregate_metrics


@dataclass(frozen=True, slots=True)
class ComparableCase:
    status: JobStatus
    latency_ms: int | None
    metrics: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ComparableRun:
    dataset_version_id: UUID
    cases: dict[str, ComparableCase]


@dataclass(frozen=True, slots=True)
class ChangedCase:
    case_id: str
    metric_deltas: dict[str, float]
    latency_delta_ms: int | None


@dataclass(frozen=True, slots=True)
class RunComparison:
    warning: str | None
    intersection_count: int
    left_only_count: int
    right_only_count: int
    left_summary: MetricsSummary
    right_summary: MetricsSummary
    metric_deltas: dict[str, float]
    only_left_failed: tuple[str, ...]
    only_right_failed: tuple[str, ...]
    changed_cases: tuple[ChangedCase, ...]


def compare_runs(left: ComparableRun, right: ComparableRun) -> RunComparison:
    if not left.cases or not right.cases:
        raise ValueError("both Runs must contain at least one case")
    left_ids = set(left.cases)
    right_ids = set(right.cases)
    intersection = left_ids & right_ids
    left_summary = _summary(left)
    right_summary = _summary(right)
    changed: list[ChangedCase] = []
    only_left_failed: list[str] = []
    only_right_failed: list[str] = []
    for case_id in sorted(intersection):
        left_case = left.cases[case_id]
        right_case = right.cases[case_id]
        if left_case.status is JobStatus.FAILED and right_case.status is not JobStatus.FAILED:
            only_left_failed.append(case_id)
        if right_case.status is JobStatus.FAILED and left_case.status is not JobStatus.FAILED:
            only_right_failed.append(case_id)
        deltas = _case_metric_deltas(left_case.metrics, right_case.metrics)
        latency_delta = (
            right_case.latency_ms - left_case.latency_ms
            if left_case.latency_ms is not None and right_case.latency_ms is not None
            else None
        )
        if deltas or (latency_delta is not None and latency_delta != 0):
            changed.append(
                ChangedCase(
                    case_id=case_id,
                    metric_deltas=deltas,
                    latency_delta_ms=latency_delta,
                )
            )
    return RunComparison(
        warning=(
            None
            if left.dataset_version_id == right.dataset_version_id
            else "dataset_versions_differ"
        ),
        intersection_count=len(intersection),
        left_only_count=len(left_ids - right_ids),
        right_only_count=len(right_ids - left_ids),
        left_summary=left_summary,
        right_summary=right_summary,
        metric_deltas=_aggregate_metric_deltas(left_summary, right_summary),
        only_left_failed=tuple(only_left_failed),
        only_right_failed=tuple(only_right_failed),
        changed_cases=tuple(changed),
    )


def _summary(run: ComparableRun) -> MetricsSummary:
    return aggregate_metrics(
        [CaseOutcome(case.status, case.latency_ms, case.metrics) for case in run.cases.values()]
    )


def _case_metric_deltas(
    left: dict[str, Any],
    right: dict[str, Any],
) -> dict[str, float]:
    deltas: dict[str, float] = {}
    for name in sorted(set(left) & set(right)):
        left_value = left[name]
        right_value = right[name]
        if (
            isinstance(left_value, bool)
            or isinstance(right_value, bool)
            or not isinstance(left_value, (int, float))
            or not isinstance(right_value, (int, float))
        ):
            continue
        delta = round(float(right_value) - float(left_value), 12)
        if delta != 0:
            deltas[name] = delta
    return deltas


def _aggregate_metric_deltas(
    left: MetricsSummary,
    right: MetricsSummary,
) -> dict[str, float]:
    deltas: dict[str, float] = {}
    for name in sorted(set(left.evaluator_metrics) & set(right.evaluator_metrics)):
        left_mean = left.evaluator_metrics[name].mean
        right_mean = right.evaluator_metrics[name].mean
        if left_mean is not None and right_mean is not None:
            deltas[name] = round(right_mean - left_mean, 12)
    return deltas
