import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from app.domain.enums import JobStatus

_TERMINAL = {
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    status: JobStatus
    latency_ms: int | None
    metrics: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Distribution:
    count: int
    mean: float | None
    p50: float | None
    p95: float | None


@dataclass(frozen=True, slots=True)
class MetricsSummary:
    total_jobs: int
    completion_rate: float
    success_rate: float
    failure_rate: float
    cancellation_rate: float
    latency: Distribution
    evaluator_metrics: dict[str, Distribution]


def aggregate_metrics(outcomes: list[CaseOutcome]) -> MetricsSummary:
    total = len(outcomes)
    if total == 0:
        raise ValueError("metrics aggregation requires at least one Job")
    terminal = sum(item.status in _TERMINAL for item in outcomes)
    succeeded = sum(item.status is JobStatus.SUCCEEDED for item in outcomes)
    failed = sum(item.status is JobStatus.FAILED for item in outcomes)
    cancelled = sum(item.status is JobStatus.CANCELLED for item in outcomes)
    latencies = [
        float(item.latency_ms)
        for item in outcomes
        if item.status is JobStatus.SUCCEEDED and item.latency_ms is not None
    ]
    metric_values: defaultdict[str, list[float]] = defaultdict(list)
    for item in outcomes:
        if item.status is not JobStatus.SUCCEEDED:
            continue
        for name, value in item.metrics.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            numeric = float(value)
            if math.isfinite(numeric):
                metric_values[name].append(numeric)
    return MetricsSummary(
        total_jobs=total,
        completion_rate=terminal / total,
        success_rate=succeeded / total,
        failure_rate=failed / total,
        cancellation_rate=cancelled / total,
        latency=_distribution(latencies),
        evaluator_metrics={
            name: _distribution(values) for name, values in sorted(metric_values.items())
        },
    )


def _distribution(values: list[float]) -> Distribution:
    if not values:
        return Distribution(count=0, mean=None, p50=None, p95=None)
    ordered = sorted(values)
    return Distribution(
        count=len(ordered),
        mean=sum(ordered) / len(ordered),
        p50=_percentile(ordered, 0.5),
        p95=_percentile(ordered, 0.95),
    )


def _percentile(ordered: list[float], probability: float) -> float:
    index = (len(ordered) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
