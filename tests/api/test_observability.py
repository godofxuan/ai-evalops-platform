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
