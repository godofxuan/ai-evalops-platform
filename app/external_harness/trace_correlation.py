"""Safe W3C correlation helpers for independently rooted evaluation traces."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Protocol

from opentelemetry.trace import Link, SpanContext, TraceFlags, TraceState

_TRACEPARENT = re.compile(
    r"^00-(?P<trace>[0-9a-f]{32})-(?P<span>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})$"
)


class SpanExporterLike(Protocol):
    def export(self, spans: Iterable[Any]) -> Any: ...


def build_remote_parent_link(traceparent: str) -> Link:
    match = _TRACEPARENT.fullmatch(traceparent)
    if match is None:
        raise ValueError("traceparent must be lowercase W3C version 00")
    trace_id = int(match.group("trace"), 16)
    span_id = int(match.group("span"), 16)
    if trace_id == 0 or span_id == 0:
        raise ValueError("W3C trace and span identifiers cannot be all zero")
    return Link(
        SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            is_remote=True,
            trace_flags=TraceFlags(int(match.group("flags"), 16) & 1),
            trace_state=TraceState(),
        )
    )


def safe_correlation_attributes(
    *,
    eval_run_id: str,
    case_id: str,
    attempt_id: str,
    producer_git_sha: str,
) -> dict[str, str]:
    values = {
        "eval.run_id": eval_run_id,
        "eval.case_id": case_id,
        "eval.attempt_id": attempt_id,
        "producer.git.sha": producer_git_sha,
    }
    if any(not value or len(value) > 200 for value in values.values()):
        raise ValueError("correlation identifiers must be non-empty and bounded")
    if not re.fullmatch(r"[0-9a-f]{40}", producer_git_sha):
        raise ValueError("producer Git SHA must be exact and lowercase")
    return values


def export_without_breaking_evaluation(
    exporter: SpanExporterLike,
    spans: Iterable[Any],
) -> bool:
    """Keep telemetry availability out of the evaluation correctness boundary."""

    try:
        exporter.export(spans)
    except Exception:
        return False
    return True


__all__ = [
    "build_remote_parent_link",
    "export_without_breaking_evaluation",
    "safe_correlation_attributes",
]
