from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from httpx import ASGITransport, AsyncClient

from app.health.service import ReadinessReport
from app.main import create_app


class ReadyProbe:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(ready=True, checks={"test": "ok"})


async def test_api_request_is_measured_traced_and_correlated_in_logs(capsys) -> None:
    application = create_app(readiness_probe=ReadyProbe())
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/health/live",
            headers={
                "X-Request-ID": "request-observability-1",
                "traceparent": ("00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"),
            },
        )
        metrics_response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-observability-1"
    assert metrics_response.status_code == 200
    assert 'api_request_total{method="GET",route="/health/live",status="200"} 1.0' in (
        metrics_response.text
    )
    output = capsys.readouterr().out
    request_record = next(
        line
        for line in output.splitlines()
        if '"event": "http_request_completed"' in line and '"path": "/health/live"' in line
    )
    assert '"request_id": "request-observability-1"' in request_record
    assert '"trace_id": "0af7651916cd43dd8448eb211c80319c"' in request_record


async def test_metrics_endpoint_refreshes_durable_outbox_backlog() -> None:
    class Result:
        def __init__(self, row: SimpleNamespace) -> None:
            self._row = row

        def one(self) -> SimpleNamespace:
            return self._row

    class Session:
        async def execute(self, statement: object) -> Result:
            sql = str(statement)
            if "evaluation_jobs" in sql:
                return Result(
                    SimpleNamespace(
                        queue_depth=0,
                        running=0,
                        oldest_heartbeat_at=None,
                    )
                )
            return Result(
                SimpleNamespace(
                    pending=3,
                    oldest_pending_at=datetime.now(UTC) - timedelta(seconds=60),
                )
            )

        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class SessionFactory:
        def __call__(self) -> Session:
            return Session()

    application = create_app(readiness_probe=ReadyProbe())
    application.state.session_factory = SessionFactory()
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "outbox_pending 3.0" in response.text
    assert "outbox_oldest_pending_age_seconds" in response.text


async def test_metrics_endpoint_exposes_durable_outbox_refresh_failures() -> None:
    class Result:
        def one(self) -> SimpleNamespace:
            return SimpleNamespace(
                queue_depth=0,
                running=0,
                oldest_heartbeat_at=None,
            )

    class SessionFactory:
        def __init__(self) -> None:
            self.executions = 0

        def __call__(self) -> "Session":
            return Session(self)

    class Session:
        def __init__(self, factory: SessionFactory) -> None:
            self._factory = factory

        async def execute(self, _statement: object) -> Result:
            self._factory.executions += 1
            if self._factory.executions == 1:
                return Result()
            raise RuntimeError("outbox metrics unavailable")

        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    application = create_app(readiness_probe=ReadyProbe())
    application.state.session_factory = SessionFactory()
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "outbox_metrics_last_success_timestamp_seconds 0.0" in response.text
    assert "outbox_metrics_refresh_failures_total 1.0" in response.text
