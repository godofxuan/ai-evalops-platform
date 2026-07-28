from dataclasses import dataclass, field

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.datasets.service import (
    DatasetNameConflictError,
    DatasetNotFoundError,
    DuplicateDatasetVersionError,
)
from app.datasets.validation import DatasetValidationError
from app.runs.service import (
    IdempotencyConflictError,
    InvalidEvaluatorConfigurationError,
    RunDatasetVersionNotFoundError,
    RunNotFoundError,
)


@dataclass(slots=True)
class APIError(Exception):
    status_code: int
    code: str
    message: str
    headers: dict[str, str] = field(default_factory=dict)


async def handle_api_error(_request: Request, exception: Exception) -> JSONResponse:
    if not isinstance(exception, APIError):
        raise exception
    error = exception
    return JSONResponse(
        status_code=error.status_code,
        headers=error.headers,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
            }
        },
    )


async def handle_request_validation_error(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, RequestValidationError):
        raise exception
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_request",
                "message": "Request validation failed.",
            }
        },
    )


async def handle_dataset_not_found(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, DatasetNotFoundError):
        raise exception
    return JSONResponse(
        status_code=404,
        content={
            "error": {
                "code": "resource_not_found",
                "message": "The requested resource was not found.",
            }
        },
    )


async def handle_dataset_validation_error(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, DatasetValidationError):
        raise exception
    error = exception
    error_body: dict[str, object] = {
        "code": error.code,
        "message": str(error),
    }
    if error.line_number is not None:
        error_body["line_number"] = error.line_number
    return JSONResponse(
        status_code=422,
        content={"error": error_body},
    )


async def handle_dataset_name_conflict(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, DatasetNameConflictError):
        raise exception
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "dataset_name_conflict",
                "message": "A dataset with this name already exists.",
            }
        },
    )


async def handle_duplicate_dataset_version(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, DuplicateDatasetVersionError):
        raise exception
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "dataset_version_exists",
                "message": "This dataset content already has a version.",
            }
        },
    )


async def handle_idempotency_conflict(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, IdempotencyConflictError):
        raise exception
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "idempotency_conflict",
                "message": "This idempotency key was used for a different request.",
            }
        },
    )


async def handle_run_not_found(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(
        exception,
        (RunNotFoundError, RunDatasetVersionNotFoundError),
    ):
        raise exception
    return JSONResponse(
        status_code=404,
        content={
            "error": {
                "code": "resource_not_found",
                "message": "The requested resource was not found.",
            }
        },
    )


async def handle_invalid_evaluator_configuration(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, InvalidEvaluatorConfigurationError):
        raise exception
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_evaluator_config",
                "message": "Evaluator configuration is invalid.",
            }
        },
    )
