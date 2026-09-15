from datetime import UTC, datetime

import httpx
import pytest

from app.observability.metrics import PlatformMetrics, start_metrics_server


def test_lease_metrics_are_scrapable_and_reject_unbounded_labels() -> None:
    metrics = PlatformMetrics()
    metrics.record_lease_authorization(operation="heartbeat", outcome="owner")
    metrics.observe_lease_lock_query(operation="result", seconds=0.25)
    metrics.observe_reaper_expiry_lag(3.0)
    for operation, outcome in (("private-job-id", "owner"), ("heartbeat", "private-answer")):
        with pytest.raises(ValueError):
            metrics.record_lease_authorization(operation=operation, outcome=outcome)
    server = start_metrics_server(metrics=metrics, host="127.0.0.1", port=0)
    try:
        port = server.server.server_address[1]
        with httpx.Client(trust_env=False, timeout=3) as client:
            response = client.get(f"http://127.0.0.1:{port}/metrics")
        assert response.status_code == 200
        assert (
            'job_lease_authorization_total{operation="heartbeat",outcome="owner"} 1.0'
            in response.text
        )
        assert 'job_lease_lock_query_seconds_sum{operation="result"} 0.25' in response.text
        assert "job_reaper_expiry_lag_seconds_sum 3.0" in response.text
        assert "private-job-id" not in response.text and "private-answer" not in response.text
    finally:
        server.close()


def test_database_operation_histograms_exist_before_the_first_observation() -> None:
    rendered = PlatformMetrics().render().decode("utf-8")

    for operation in ("claim", "result", "failure", "reaper"):
        assert f'db_operation_duration_seconds_count{{operation="{operation}"}} 0.0' in rendered


def test_metrics_registry_exposes_required_platform_signals() -> None:
    metrics = PlatformMetrics()

    metrics.observe_api_request(
        method="GET",
        route="/health/live",
        status_code=200,
        duration_seconds=0.012,
    )
    metrics.record_run_created()
    metrics.set_job_queue_depth(7)
    metrics.set_job_running(2)
    metrics.record_job_succeeded()
    metrics.record_job_failed()
    metrics.record_job_retry()
    metrics.record_job_lease_expired()
    metrics.set_worker_heartbeat_age(3.5)
    metrics.observe_case_duration(0.25)
    for operation in ("claim", "result", "failure", "reaper"):
        metrics.observe_db_operation(operation=operation, duration_seconds=0.012)
    metrics.sse_connected()
    metrics.record_redis_publish_failure()
    metrics.observe_audit_delivery_latency(0.75)

    rendered = metrics.render().decode("utf-8")

    for metric_name in (
        "api_request_total",
        "api_request_duration",
        "run_created_total",
        "job_queue_depth",
        "job_running",
        "job_succeeded_total",
        "job_failed_total",
        "job_retry_total",
        "job_lease_expired_total",
        "worker_heartbeat_age",
        "case_duration",
        "db_operation_duration",
        "sse_connections",
        "redis_publish_failures_total",
        "mcp_audit_delivery_latency_seconds",
    ):
        assert metric_name in rendered
    assert 'route="/health/live"' in rendered
    assert "tenant_id=" not in rendered
    assert "run_id=" not in rendered
    assert "job_id=" not in rendered
    for operation in ("claim", "result", "failure", "reaper"):
        assert f'db_operation_duration_seconds_count{{operation="{operation}"}} 1.0' in rendered


def test_sse_connection_gauge_returns_to_zero_after_disconnect() -> None:
    metrics = PlatformMetrics()

    metrics.sse_connected()
    metrics.sse_disconnected()

    assert "sse_connections 0.0" in metrics.render().decode("utf-8")


def test_outbox_backlog_gauges_are_global_and_low_cardinality() -> None:
    metrics = PlatformMetrics()

    metrics.set_outbox_pending(3)
    metrics.set_outbox_oldest_pending_age(42.5)

    rendered = metrics.render().decode("utf-8")
    assert "outbox_pending 3.0" in rendered
    assert "outbox_oldest_pending_age_seconds 42.5" in rendered
    assert "tenant_id=" not in rendered
    assert "run_id=" not in rendered
    assert "event_id=" not in rendered


def test_outbox_metrics_refresh_success_timestamp_is_global_and_low_cardinality() -> None:
    metrics = PlatformMetrics()

    metrics.record_outbox_metrics_refresh_success(datetime.fromtimestamp(123.5, tz=UTC))

    rendered = metrics.render().decode("utf-8")
    assert "outbox_metrics_last_success_timestamp_seconds 123.5" in rendered
    assert "tenant_id=" not in rendered
    assert "run_id=" not in rendered
    assert "event_id=" not in rendered


def test_outbox_metrics_refresh_failures_are_global_and_low_cardinality() -> None:
    metrics = PlatformMetrics()

    metrics.record_outbox_metrics_refresh_failure()

    rendered = metrics.render().decode("utf-8")
    assert "outbox_metrics_refresh_failures_total 1.0" in rendered
    assert "tenant_id=" not in rendered
    assert "run_id=" not in rendered
    assert "event_id=" not in rendered


def test_outbox_operation_counters_record_bounded_global_totals() -> None:
    metrics = PlatformMetrics()

    metrics.record_outbox_retry_scheduled(2)
    metrics.record_outbox_lease_lost(1)
    metrics.record_outbox_cleanup_deleted(5)

    rendered = metrics.render().decode("utf-8")
    assert "outbox_retry_scheduled_total 2.0" in rendered
    assert "outbox_lease_lost_total 1.0" in rendered
    assert "outbox_cleanup_deleted_total 5.0" in rendered
    assert "tenant_id=" not in rendered
    assert "event_id=" not in rendered
