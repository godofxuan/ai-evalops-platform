from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from app.api.errors import APIError
from app.auth.dependencies import get_principal
from app.auth.principals import Principal
from app.core.config import Settings
from app.datasets.schemas import DatasetCreate, DatasetRead, DatasetVersionRead
from app.datasets.service import DatasetService

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])
SUPPORTED_JSONL_MEDIA_TYPES = frozenset(
    {
        "application/jsonl",
        "application/x-ndjson",
    }
)


@router.post("", response_model=DatasetRead, status_code=status.HTTP_201_CREATED)
async def create_dataset(
    payload: DatasetCreate,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> DatasetRead:
    service = cast(DatasetService | None, request.app.state.dataset_service)
    if service is None:
        raise RuntimeError("dataset service is not configured")
    return await service.create_dataset(principal=principal, request=payload)


@router.get("/{dataset_id}", response_model=DatasetRead)
async def get_dataset(
    dataset_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> DatasetRead:
    service = cast(DatasetService | None, request.app.state.dataset_service)
    if service is None:
        raise RuntimeError("dataset service is not configured")
    return await service.get_dataset(principal=principal, dataset_id=dataset_id)


@router.post(
    "/{dataset_id}/versions",
    response_model=DatasetVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_dataset_version(
    dataset_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    file: Annotated[UploadFile, File(description="A bounded UTF-8 JSONL dataset")],
) -> DatasetVersionRead:
    media_type = (file.content_type or "").partition(";")[0].strip().lower()
    if media_type not in SUPPORTED_JSONL_MEDIA_TYPES:
        raise APIError(
            status_code=415,
            code="unsupported_media_type",
            message="A supported JSONL media type is required.",
        )

    settings = cast(Settings, request.app.state.settings)
    content = await file.read(settings.dataset_max_file_bytes + 1)
    if len(content) > settings.dataset_max_file_bytes:
        raise APIError(
            status_code=413,
            code="file_too_large",
            message="Dataset file exceeds the configured size limit.",
        )

    service = cast(DatasetService | None, request.app.state.dataset_service)
    if service is None:
        raise RuntimeError("dataset service is not configured")
    return await service.create_dataset_version(
        principal=principal,
        dataset_id=dataset_id,
        content=content,
        media_type=media_type,
    )


@router.get(
    "/{dataset_id}/versions/{version_id}",
    response_model=DatasetVersionRead,
)
async def get_dataset_version(
    dataset_id: UUID,
    version_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> DatasetVersionRead:
    service = cast(DatasetService | None, request.app.state.dataset_service)
    if service is None:
        raise RuntimeError("dataset service is not configured")
    return await service.get_dataset_version(
        principal=principal,
        dataset_id=dataset_id,
        version_id=version_id,
    )
