from dataclasses import dataclass
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

    def set_worker_heartbeat_age(self, seconds: float) -> None:
        self._worker_heartbeat_age.set(max(seconds, 0.0))

    def observe_case_duration(self, seconds: float) -> None:
        self._case_duration.observe(max(seconds, 0.0))

    def sse_connected(self) -> None:
        self._sse_connections.inc()

    def sse_disconnected(self) -> None:
        self._sse_connections.dec()

    def record_redis_publish_failure(self) -> None:
        self._redis_publish_failures.inc()

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
