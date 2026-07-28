from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import get_api_key_lookup, get_principal
from app.auth.principals import Principal
from app.core.config import Settings
from app.datasets.schemas import DatasetCreate, DatasetRead
from app.datasets.service import (
    DatasetNameConflictError,
    DatasetNotFoundError,
    DuplicateDatasetVersionError,
)
from app.datasets.validation import DatasetValidationError
from app.main import create_app


async def test_create_dataset_requires_bearer_api_key() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/datasets",
            json={"name": "rag-regression", "description": "Regression cases"},
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "error": {
            "code": "invalid_api_key",
            "message": "Authentication credentials are invalid.",
        }
    }


class UnknownAPIKeyLookup:
    async def find_by_prefix(self, _prefix: str) -> None:
        return None

    async def mark_used(self, _api_key_id: object, *, used_at: object) -> bool:
        raise AssertionError(f"unknown API key cannot be marked used at {used_at}")


@pytest.mark.parametrize(
    "plaintext",
    [
        "not-an-api-key",
        "evk_001122334455_abcdefghijklmnopqrstuvwxyzABCDEFGH123456789",
    ],
    ids=["malformed", "unknown-prefix"],
)
async def test_create_dataset_uses_same_error_for_invalid_api_keys(plaintext: str) -> None:
    application = create_app()
    application.dependency_overrides[get_api_key_lookup] = UnknownAPIKeyLookup
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/datasets",
            headers={"Authorization": f"Bearer {plaintext}"},
            json={"name": "rag-regression"},
        )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "invalid_api_key",
            "message": "Authentication credentials are invalid.",
        }
    }


class DatasetServiceThatMustNotBeCalled:
    async def create_dataset(self, **_kwargs: object) -> None:
        raise AssertionError("invalid request must not reach the dataset service")


async def test_create_dataset_rejects_client_supplied_tenant_id() -> None:
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: Principal(
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        key_prefix="evk_001122334455",
    )
    application.state.dataset_service = DatasetServiceThatMustNotBeCalled()
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/datasets",
            json={
                "name": "rag-regression",
                "description": "Regression cases",
                "tenant_id": "00000000-0000-0000-0000-000000000999",
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_request",
            "message": "Request validation failed.",
        }
    }


class RecordingDatasetService:
    def __init__(self) -> None:
        self.created_with: tuple[Principal, DatasetCreate] | None = None
        self.requested_with: tuple[Principal, UUID] | None = None
        self.version_created_with: tuple[Principal, UUID, bytes, str] | None = None
        self.version_requested_with: tuple[Principal, UUID, UUID] | None = None

    async def create_dataset(
        self,
        *,
        principal: Principal,
        request: DatasetCreate,
    ) -> DatasetRead:
        self.created_with = (principal, request)
        return DatasetRead(
            id=UUID("00000000-0000-0000-0000-000000000301"),
            name=request.name,
            description=request.description,
            created_at=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
        )

    async def get_dataset(
        self,
        *,
        principal: Principal,
        dataset_id: UUID,
    ) -> DatasetRead:
        self.requested_with = (principal, dataset_id)
        return DatasetRead(
            id=dataset_id,
            name="rag-regression",
            description="Regression cases",
            created_at=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
        )

    async def create_dataset_version(
        self,
        *,
        principal: Principal,
        dataset_id: UUID,
        content: bytes,
        media_type: str,
    ) -> object:
        self.version_created_with = (principal, dataset_id, content, media_type)
        return {
            "id": "00000000-0000-0000-0000-000000000401",
            "dataset_id": str(dataset_id),
            "version": 1,
            "schema_version": "1",
            "sha256": "a" * 64,
            "case_count": 1,
            "artifact_id": "00000000-0000-0000-0000-000000000501",
            "created_at": "2026-07-29T10:05:00Z",
        }

    async def get_dataset_version(
        self,
        *,
        principal: Principal,
        dataset_id: UUID,
        version_id: UUID,
    ) -> object:
        self.version_requested_with = (principal, dataset_id, version_id)
        return {
            "id": str(version_id),
            "dataset_id": str(dataset_id),
            "version": 1,
            "schema_version": "1",
            "sha256": "a" * 64,
            "case_count": 1,
            "artifact_id": "00000000-0000-0000-0000-000000000501",
            "created_at": "2026-07-29T10:05:00Z",
        }


async def test_create_dataset_uses_server_principal_and_returns_metadata() -> None:
    principal = Principal(
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        key_prefix="evk_001122334455",
    )
    service = RecordingDatasetService()
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: principal
    application.state.dataset_service = service
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/datasets",
            json={"name": "  rag-regression  ", "description": "Regression cases"},
        )

    assert response.status_code == 201
    assert response.json() == {
        "id": "00000000-0000-0000-0000-000000000301",
        "name": "rag-regression",
        "description": "Regression cases",
        "created_at": "2026-07-29T10:00:00Z",
    }
    assert service.created_with is not None
    used_principal, used_request = service.created_with
    assert used_principal == principal
    assert used_request.name == "rag-regression"


async def test_get_dataset_uses_server_principal_and_resource_id() -> None:
    principal = Principal(
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        key_prefix="evk_001122334455",
    )
    dataset_id = UUID("00000000-0000-0000-0000-000000000301")
    service = RecordingDatasetService()
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: principal
    application.state.dataset_service = service
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/datasets/{dataset_id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(dataset_id)
    assert service.requested_with == (principal, dataset_id)


class MissingDatasetService(RecordingDatasetService):
    async def get_dataset(
        self,
        *,
        principal: Principal,
        dataset_id: UUID,
    ) -> DatasetRead:
        raise DatasetNotFoundError


async def test_get_dataset_hides_missing_and_cross_tenant_resources() -> None:
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: Principal(
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        key_prefix="evk_001122334455",
    )
    application.state.dataset_service = MissingDatasetService()
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/datasets/00000000-0000-0000-0000-000000000999")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "resource_not_found",
            "message": "The requested resource was not found.",
        }
    }


async def test_upload_dataset_version_passes_bounded_jsonl_to_tenant_service() -> None:
    principal = Principal(
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        key_prefix="evk_001122334455",
    )
    dataset_id = UUID("00000000-0000-0000-0000-000000000301")
    content = b'{"case_id":"case-1","question":"q","expected_answer":"a","metadata":{}}\n'
    service = RecordingDatasetService()
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: principal
    application.state.dataset_service = service
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/datasets/{dataset_id}/versions",
            files={"file": ("cases.jsonl", content, "application/x-ndjson")},
        )

    assert response.status_code == 201
    assert response.json() == {
        "id": "00000000-0000-0000-0000-000000000401",
        "dataset_id": str(dataset_id),
        "version": 1,
        "schema_version": "1",
        "sha256": "a" * 64,
        "case_count": 1,
        "artifact_id": "00000000-0000-0000-0000-000000000501",
        "created_at": "2026-07-29T10:05:00Z",
    }
    assert service.version_created_with == (
        principal,
        dataset_id,
        content,
        "application/x-ndjson",
    )


async def test_upload_dataset_version_rejects_unsupported_media_type() -> None:
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: Principal(
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        key_prefix="evk_001122334455",
    )
    application.state.dataset_service = DatasetServiceThatMustNotBeCalled()
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/datasets/00000000-0000-0000-0000-000000000301/versions",
            files={"file": ("cases.txt", b"not jsonl", "text/plain")},
        )

    assert response.status_code == 415
    assert response.json() == {
        "error": {
            "code": "unsupported_media_type",
            "message": "A supported JSONL media type is required.",
        }
    }


async def test_upload_dataset_version_reads_only_enough_to_detect_oversize() -> None:
    settings = Settings(
        _env_file=None,
        dataset_max_file_bytes=8,
        dataset_max_line_bytes=8,
    )
    application = create_app(settings=settings)
    application.dependency_overrides[get_principal] = lambda: Principal(
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        key_prefix="evk_001122334455",
    )
    application.state.dataset_service = DatasetServiceThatMustNotBeCalled()
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/datasets/00000000-0000-0000-0000-000000000301/versions",
            files={"file": ("cases.jsonl", b"123456789", "application/jsonl")},
        )

    assert response.status_code == 413
    assert response.json() == {
        "error": {
            "code": "file_too_large",
            "message": "Dataset file exceeds the configured size limit.",
        }
    }


class InvalidDatasetVersionService(RecordingDatasetService):
    async def create_dataset_version(
        self,
        *,
        principal: Principal,
        dataset_id: UUID,
        content: bytes,
        media_type: str,
    ) -> object:
        raise DatasetValidationError(
            "invalid_json",
            "dataset line is not valid JSON",
            line_number=2,
        )


async def test_upload_dataset_version_maps_validation_error_without_echoing_content() -> None:
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: Principal(
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        key_prefix="evk_001122334455",
    )
    application.state.dataset_service = InvalidDatasetVersionService()
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/datasets/00000000-0000-0000-0000-000000000301/versions",
            files={
                "file": (
                    "cases.jsonl",
                    b'{"sensitive":"must-not-be-echoed"}\ninvalid',
                    "application/jsonl",
                )
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_json",
            "message": "dataset line is not valid JSON",
            "line_number": 2,
        }
    }
    assert "must-not-be-echoed" not in response.text


async def test_get_dataset_version_uses_full_tenant_resource_chain() -> None:
    principal = Principal(
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        key_prefix="evk_001122334455",
    )
    dataset_id = UUID("00000000-0000-0000-0000-000000000301")
    version_id = UUID("00000000-0000-0000-0000-000000000401")
    service = RecordingDatasetService()
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: principal
    application.state.dataset_service = service
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/datasets/{dataset_id}/versions/{version_id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(version_id)
    assert service.version_requested_with == (principal, dataset_id, version_id)


class ConflictingDatasetService(RecordingDatasetService):
    async def create_dataset(
        self,
        *,
        principal: Principal,
        request: DatasetCreate,
    ) -> DatasetRead:
        raise DatasetNameConflictError


async def test_create_dataset_maps_same_tenant_name_conflict() -> None:
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: Principal(
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        key_prefix="evk_001122334455",
    )
    application.state.dataset_service = ConflictingDatasetService()
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/datasets",
            json={"name": "rag-regression"},
        )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "dataset_name_conflict",
            "message": "A dataset with this name already exists.",
        }
    }


class DuplicateVersionService(RecordingDatasetService):
    async def create_dataset_version(
        self,
        *,
        principal: Principal,
        dataset_id: UUID,
        content: bytes,
        media_type: str,
    ) -> object:
        raise DuplicateDatasetVersionError


async def test_upload_dataset_version_maps_duplicate_content_conflict() -> None:
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: Principal(
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        key_prefix="evk_001122334455",
    )
    application.state.dataset_service = DuplicateVersionService()
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/datasets/00000000-0000-0000-0000-000000000301/versions",
            files={
                "file": (
                    "cases.jsonl",
                    b'{"case_id":"case-1"}\n',
                    "application/jsonl",
                )
            },
        )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "dataset_version_exists",
            "message": "This dataset content already has a version.",
        }
    }
