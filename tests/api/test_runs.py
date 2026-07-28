from datetime import UTC, datetime
from uuid import UUID

from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import get_principal
from app.auth.principals import Principal
from app.main import create_app
from app.runs.schemas import RunCreate, RunRead
from app.runs.service import (
    IdempotencyConflictError,
    InvalidEvaluatorConfigurationError,
    RunNotFoundError,
)

PRINCIPAL = Principal(
    tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
    api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
    key_prefix="evk_001122334455",
)


async def test_create_run_requires_idempotency_key() -> None:
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: PRINCIPAL
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/runs",
            json={
                "dataset_version_id": "00000000-0000-0000-0000-000000000401",
                "target": {"type": "mock"},
                "evaluator": {
                    "type": "basic_answer",
                    "config": {"max_attempts": 3},
                },
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_request",
            "message": "Request validation failed.",
        }
    }


class RecordingRunService:
    def __init__(self) -> None:
        self.created_with: tuple[Principal, str, RunCreate] | None = None
        self.requested_with: tuple[Principal, UUID] | None = None

    async def create_run(
        self,
        *,
        principal: Principal,
        idempotency_key: str,
        request: RunCreate,
    ) -> RunRead:
        self.created_with = (principal, idempotency_key, request)
        return RunRead(
            id=UUID("00000000-0000-0000-0000-000000000601"),
            dataset_version_id=request.dataset_version_id,
            status="queued",
            total_jobs=2,
            succeeded_jobs=0,
            failed_jobs=0,
            cancelled_jobs=0,
            created_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
            started_at=None,
            finished_at=None,
        )

    async def get_run(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> RunRead:
        self.requested_with = (principal, run_id)
        return RunRead(
            id=run_id,
            dataset_version_id=UUID("00000000-0000-0000-0000-000000000401"),
            status="queued",
            total_jobs=2,
            succeeded_jobs=0,
            failed_jobs=0,
            cancelled_jobs=0,
            created_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
            started_at=None,
            finished_at=None,
        )


async def test_create_run_passes_server_principal_and_idempotency_key() -> None:
    service = RecordingRunService()
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: PRINCIPAL
    application.state.run_service = service
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/runs",
            headers={"Idempotency-Key": "create-rag-v1"},
            json={
                "dataset_version_id": "00000000-0000-0000-0000-000000000401",
                "target": {"type": "mock"},
                "evaluator": {
                    "type": "basic_answer",
                    "config": {"max_attempts": 3},
                },
            },
        )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert service.created_with is not None
    principal, idempotency_key, request = service.created_with
    assert principal == PRINCIPAL
    assert idempotency_key == "create-rag-v1"
    assert request.dataset_version_id == UUID("00000000-0000-0000-0000-000000000401")


async def test_get_run_passes_server_principal_to_service() -> None:
    run_id = UUID("00000000-0000-0000-0000-000000000601")
    service = RecordingRunService()
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: PRINCIPAL
    application.state.run_service = service
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/runs/{run_id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(run_id)
    assert service.requested_with == (PRINCIPAL, run_id)


class ConflictingRunService(RecordingRunService):
    async def create_run(
        self,
        *,
        principal: Principal,
        idempotency_key: str,
        request: RunCreate,
    ) -> RunRead:
        raise IdempotencyConflictError


async def test_create_run_maps_idempotency_payload_conflict_to_409() -> None:
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: PRINCIPAL
    application.state.run_service = ConflictingRunService()
    transport = ASGITransport(app=application, raise_app_exceptions=False)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/runs",
            headers={"Idempotency-Key": "create-rag-v1"},
            json={
                "dataset_version_id": "00000000-0000-0000-0000-000000000401",
                "target": {"type": "mock"},
                "evaluator": {"type": "basic_answer"},
            },
        )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "idempotency_conflict",
            "message": "This idempotency key was used for a different request.",
        }
    }


class MissingRunService(RecordingRunService):
    async def get_run(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> RunRead:
        raise RunNotFoundError


async def test_get_run_hides_missing_and_cross_tenant_resources() -> None:
    run_id = UUID("00000000-0000-0000-0000-000000000601")
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: PRINCIPAL
    application.state.run_service = MissingRunService()
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/runs/{run_id}")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "resource_not_found",
            "message": "The requested resource was not found.",
        }
    }


class InvalidEvaluatorRunService(RecordingRunService):
    async def create_run(
        self,
        *,
        principal: Principal,
        idempotency_key: str,
        request: RunCreate,
    ) -> RunRead:
        raise InvalidEvaluatorConfigurationError


async def test_create_run_maps_invalid_evaluator_configuration_to_422() -> None:
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: PRINCIPAL
    application.state.run_service = InvalidEvaluatorRunService()
    transport = ASGITransport(app=application, raise_app_exceptions=False)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/runs",
            headers={"Idempotency-Key": "invalid-evaluator"},
            json={
                "dataset_version_id": "00000000-0000-0000-0000-000000000401",
                "target": {"type": "mock"},
                "evaluator": {"type": "basic_answer"},
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_evaluator_config",
            "message": "Evaluator configuration is invalid.",
        }
    }
