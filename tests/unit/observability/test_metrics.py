from datetime import UTC, datetime

from app.observability.metrics import PlatformMetrics


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
