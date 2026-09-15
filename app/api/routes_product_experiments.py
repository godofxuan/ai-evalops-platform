from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status

from app.api.errors import APIError
from app.api.product_submission_body import experiment_submission_schema, read_experiment_submission
from app.auth.dependencies import get_principal
from app.auth.principals import Principal
from app.product_experiments.export_schemas import (
    PrivateDurableReport,
    PublicDurableReport,
    project_public_durable_report,
)
from app.product_experiments.export_service import ProductReportExporter, encode_report
from app.product_experiments.report_persistence import ReportPublicationConflictError
from app.product_experiments.result_snapshot import ExperimentNotTerminalError
from app.product_experiments.service import (
    ExperimentSubmissionAccepted,
    ProductExperimentRead,
    ProductExperimentService,
)
from app.product_experiments.spec import InputLimitError
from app.product_experiments.submission import DurableExperimentSubmitter
from app.runs.service import RunInputIntegrityError

router = APIRouter(prefix="/api/v1/experiments", tags=["product-experiments"])


@router.post("/{experiment_id}/export", response_model=PublicDurableReport | PrivateDurableReport)
async def export_experiment(
    experiment_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    include_private: bool = False,
) -> Response:
    exporter = cast(
        ProductReportExporter | None,
        getattr(request.app.state, "product_experiment_exporter", None),
    )
    if exporter is None:
        raise APIError(503, "experiment_export_unavailable", "Experiment export is not available.")
    try:
        exported = await exporter.export(principal=principal, experiment_id=experiment_id)
        payload = (
            exported.payload
            if include_private
            else encode_report(project_public_durable_report(exported).model_dump(mode="json"))
        )
    except ExperimentNotTerminalError:
        raise APIError(409, "experiment_not_terminal", "Experiment is still executing.") from None
    except ReportPublicationConflictError:
        raise APIError(
            409, "experiment_report_conflict", "A different immutable report is already published."
        ) from None
    except ValueError:
        raise APIError(
            422, "experiment_export_invalid", "Experiment evidence cannot support this export."
        ) from None
    return Response(
        content=payload,
        media_type="application/json",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": 'attachment; filename="experiment-private.json"'
            if include_private
            else 'attachment; filename="experiment-public.json"',
        },
    )


@router.post(
    "",
    response_model=ExperimentSubmissionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": experiment_submission_schema()}},
        }
    },
)
async def submit_experiment(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9._:-]{1,128}$")
    ],
) -> ExperimentSubmissionAccepted:
    submitter = cast(
        DurableExperimentSubmitter | None,
        getattr(request.app.state, "product_experiment_submitter", None),
    )
    if submitter is None:
        raise APIError(
            503, "experiment_submission_unavailable", "Experiment submission is not enabled."
        )
    experiment_request, dataset_payload = await read_experiment_submission(request)
    try:
        experiment = await submitter.submit(
            principal=principal,
            idempotency_key=idempotency_key,
            request=experiment_request,
            dataset_payload=dataset_payload,
        )
    except (RunInputIntegrityError, InputLimitError):
        raise APIError(
            422, "invalid_experiment_input", "Experiment input validation failed."
        ) from None
    return ExperimentSubmissionAccepted(
        id=experiment.id,
        baseline_run_id=experiment.baseline_run_id,
        candidate_run_id=experiment.candidate_run_id,
        status_url=f"/api/v1/experiments/{experiment.id}",
    )


def _service(request: Request) -> ProductExperimentService:
    service = cast(ProductExperimentService | None, request.app.state.product_experiment_service)
    if service is None:
        raise RuntimeError("product experiment service is not configured")
    return service


@router.get("/{experiment_id}", response_model=ProductExperimentRead)
async def get_experiment(
    experiment_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> ProductExperimentRead:
    return await _service(request).get(principal=principal, experiment_id=experiment_id)


@router.post(
    "/{experiment_id}/cancel",
    response_model=ProductExperimentRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_experiment(
    experiment_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> ProductExperimentRead:
    return await _service(request).cancel(principal=principal, experiment_id=experiment_id)
