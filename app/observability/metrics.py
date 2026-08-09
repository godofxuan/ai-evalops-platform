from dataclasses import dataclass
from datetime import datetime
from socketserver import BaseServer
from threading import Thread

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server,
)

DB_OPERATIONS = frozenset({"claim", "result", "failure", "reaper"})


class PlatformMetrics:
    """Own one Prometheus registry per process.

    Identifiers such as tenant, Run, Job, and Attempt IDs are deliberately absent
    from labels. They belong in traces and logs; using them as labels would create
    an unbounded number of Prometheus time series.
    """

    content_type = CONTENT_TYPE_LATEST

    def __init__(self, *, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self._api_request_total = Counter(
            "api_request_total",
            "Completed HTTP requests.",
            ("method", "route", "status"),
            registry=self.registry,
        )
        self._api_request_duration = Histogram(
            "api_request_duration",
            "HTTP request duration in seconds.",
            ("method", "route"),
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
            registry=self.registry,
        )
        self._run_created_total = Counter(
            "run_created_total",
            "New Runs durably created; idempotency replays are excluded.",
            registry=self.registry,
        )
        self._job_queue_depth = Gauge(
            "job_queue_depth",
            "Jobs currently eligible or waiting to become eligible.",
            registry=self.registry,
        )
        self._job_running = Gauge(
            "job_running",
            "Jobs currently holding a running lease.",
            registry=self.registry,
        )
        self._job_succeeded_total = Counter(
            "job_succeeded_total",
            "Jobs successfully persisted by this process.",
            registry=self.registry,
        )
        self._job_failed_total = Counter(
            "job_failed_total",
            "Jobs permanently failed by this process.",
            registry=self.registry,
        )
        self._job_retry_total = Counter(
            "job_retry_total",
            "Retry transitions committed by this process.",
            registry=self.registry,
        )
        self._job_lease_expired_total = Counter(
            "job_lease_expired_total",
            "Expired leases recovered by this process.",
            registry=self.registry,
        )
        self._tenant_turn_reserved = Counter(
            "tenant_turn_reserved",
            "Fair Tenant turns durably reserved by this scheduler process.",
            registry=self.registry,
        )
        self._tenant_turn_without_job = Counter(
            "tenant_turn_without_job",
            "Reserved Tenant turns whose Phase B found no claimable Job.",
            registry=self.registry,
        )
        self._reservation_miss_rate = Gauge(
            "reservation_miss_rate",
            "Tenant turns without a Job divided by all reserved Tenant turns in this process.",
            registry=self.registry,
        )
        self._tenant_turn_reserved_count = 0
        self._tenant_turn_without_job_count = 0
        self._worker_heartbeat_age = Gauge(
            "worker_heartbeat_age",
            "Age in seconds of the stalest running Job heartbeat.",
            registry=self.registry,
        )
        self._case_duration = Histogram(
            "case_duration",
            "Target plus evaluator case duration in seconds.",
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
            registry=self.registry,
        )
        self._db_operation_duration = Histogram(
            "db_operation_duration_seconds",
            "Observed duration of bounded durable database operations.",
            ("operation",),
            buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
            registry=self.registry,
        )
        for operation in sorted(DB_OPERATIONS):
            self._db_operation_duration.labels(operation=operation)
        self._sse_connections = Gauge(
            "sse_connections",
            "Currently open SSE response iterators.",
            registry=self.registry,
        )
        self._redis_publish_failures = Counter(
            "redis_publish_failures",
            "Best-effort Redis progress publications that failed.",
            registry=self.registry,
        )
        self._outbox_pending = Gauge(
            "outbox_pending",
            "Durable progress events awaiting successful publication.",
            registry=self.registry,
        )
        self._outbox_oldest_pending_age = Gauge(
            "outbox_oldest_pending_age_seconds",
            "Age of the oldest durable unpublished progress event.",
            registry=self.registry,
        )
        self._outbox_metrics_last_success_timestamp = Gauge(
            "outbox_metrics_last_success_timestamp_seconds",
            "Unix timestamp of the most recent successful durable Outbox metrics refresh.",
            registry=self.registry,
        )
        self._outbox_metrics_refresh_failures = Counter(
            "outbox_metrics_refresh_failures",
            "Durable Outbox metrics refreshes that failed in this process.",
            registry=self.registry,
        )
        self._outbox_retry_scheduled = Counter(
            "outbox_retry_scheduled",
            "Durable progress publications rescheduled after a failed attempt.",
            registry=self.registry,
        )
        self._outbox_lease_lost = Counter(
            "outbox_lease_lost",
            "Outbox publications whose acknowledgement or reschedule lost its lease.",
            registry=self.registry,
        )
        self._outbox_cleanup_deleted = Counter(
            "outbox_cleanup_deleted",
            "Published Outbox rows deleted after the configured retention period.",
            registry=self.registry,
        )

    def observe_api_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        self._api_request_total.labels(
            method=method,
            route=route,
            status=str(status_code),
        ).inc()
        self._api_request_duration.labels(method=method, route=route).observe(duration_seconds)

    def record_run_created(self) -> None:
        self._run_created_total.inc()

    def set_job_queue_depth(self, value: int) -> None:
        self._job_queue_depth.set(value)

    def set_job_running(self, value: int) -> None:
        self._job_running.set(value)

    def record_job_succeeded(self) -> None:
        self._job_succeeded_total.inc()

    def record_job_failed(self) -> None:
        self._job_failed_total.inc()

    def record_job_retry(self) -> None:
        self._job_retry_total.inc()

    def record_job_lease_expired(self, count: int = 1) -> None:
        if count > 0:
            self._job_lease_expired_total.inc(count)

    def record_tenant_turn_reserved(self) -> None:
        self._tenant_turn_reserved.inc()
        self._tenant_turn_reserved_count += 1
        self._update_reservation_miss_rate()

    def record_tenant_turn_without_job(self) -> None:
        self._tenant_turn_without_job.inc()
        self._tenant_turn_without_job_count += 1
        self._update_reservation_miss_rate()

    def _update_reservation_miss_rate(self) -> None:
        denominator = self._tenant_turn_reserved_count
        rate = self._tenant_turn_without_job_count / denominator if denominator else 0.0
        self._reservation_miss_rate.set(rate)

    def set_worker_heartbeat_age(self, seconds: float) -> None:
        self._worker_heartbeat_age.set(max(seconds, 0.0))

    def observe_case_duration(self, seconds: float) -> None:
        self._case_duration.observe(max(seconds, 0.0))

    def observe_db_operation(self, *, operation: str, duration_seconds: float) -> None:
        if operation not in DB_OPERATIONS:
            raise ValueError(f"unsupported database operation metric: {operation}")
        self._db_operation_duration.labels(operation=operation).observe(max(duration_seconds, 0.0))

    def sse_connected(self) -> None:
        self._sse_connections.inc()

    def sse_disconnected(self) -> None:
        self._sse_connections.dec()

    def record_redis_publish_failure(self) -> None:
        self._redis_publish_failures.inc()

    def set_outbox_pending(self, value: int) -> None:
        self._outbox_pending.set(max(value, 0))

    def set_outbox_oldest_pending_age(self, seconds: float) -> None:
        self._outbox_oldest_pending_age.set(max(seconds, 0.0))

    def record_outbox_metrics_refresh_success(self, observed_at: datetime) -> None:
        self._outbox_metrics_last_success_timestamp.set(observed_at.timestamp())

    def record_outbox_metrics_refresh_failure(self) -> None:
        self._outbox_metrics_refresh_failures.inc()

    def record_outbox_retry_scheduled(self, count: int = 1) -> None:
        if count > 0:
            self._outbox_retry_scheduled.inc(count)

    def record_outbox_lease_lost(self, count: int = 1) -> None:
        if count > 0:
            self._outbox_lease_lost.inc(count)

    def record_outbox_cleanup_deleted(self, count: int) -> None:
        if count > 0:
            self._outbox_cleanup_deleted.inc(count)

    def render(self) -> bytes:
        return generate_latest(self.registry)


@dataclass(slots=True)
class MetricsServer:
    server: BaseServer
    thread: Thread

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def start_metrics_server(
    *,
    metrics: PlatformMetrics,
    host: str,
    port: int,
) -> MetricsServer:
    server, thread = start_http_server(
        port=port,
        addr=host,
        registry=metrics.registry,
    )
    return MetricsServer(server=server, thread=thread)
