from uuid import UUID

from httpx import ASGITransport, AsyncClient

from app.health.service import ComponentCheck, ReadinessReport
from app.main import create_app


async def test_liveness_reports_that_the_api_process_is_alive() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


async def test_response_contains_a_server_generated_request_id() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")

    request_id = response.headers["x-request-id"]
    assert str(UUID(request_id)) == request_id


class AlwaysReadyProbe:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(
            status="ready",
            checks={
                "postgresql": ComponentCheck(status="ok"),
                "redis": ComponentCheck(status="ok"),
                "artifacts": ComponentCheck(status="ok"),
                "migrations": ComponentCheck(status="ok"),
            },
        )


class AlwaysNotReadyProbe:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(
            status="not_ready",
            checks={
                "postgresql": ComponentCheck(
                    status="error",
                    error_code="postgresql_unavailable",
                )
            },
        )


async def test_readiness_reports_each_healthy_dependency() -> None:
    transport = ASGITransport(app=create_app(readiness_probe=AlwaysReadyProbe()))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "postgresql": {"status": "ok", "error_code": None},
            "redis": {"status": "ok", "error_code": None},
            "artifacts": {"status": "ok", "error_code": None},
            "migrations": {"status": "ok", "error_code": None},
        },
    }


async def test_readiness_returns_service_unavailable_with_a_stable_error_code() -> None:
    transport = ASGITransport(app=create_app(readiness_probe=AlwaysNotReadyProbe()))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "postgresql": {
                "status": "error",
                "error_code": "postgresql_unavailable",
            }
        },
    }
