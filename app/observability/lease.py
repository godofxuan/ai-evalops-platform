"""Bounded lease telemetry; no extra SQL, identifiers, or authorization decisions."""

from collections.abc import Awaitable
from time import perf_counter

from app.observability.metrics import PlatformMetrics


def record_lease_decision(metrics: PlatformMetrics | None, operation: str, outcome: str) -> None:
    if metrics is not None:
        metrics.record_lease_authorization(operation=operation, outcome=outcome)


async def observe_lease_lock_query[T](
    query: Awaitable[T], *, metrics: PlatformMetrics | None, operation: str
) -> T:
    """Include query/network/scheduling overhead, NOT pure server lock-wait time."""
    if metrics is None:
        return await query
    started = perf_counter()
    try:
        return await query
    finally:
        metrics.observe_lease_lock_query(operation=operation, seconds=perf_counter() - started)
