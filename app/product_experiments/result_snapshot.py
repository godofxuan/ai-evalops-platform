"""Freeze durable outcomes without treating a historical attempt as an accepted result."""

from copy import deepcopy
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import load_only

from app.domain.enums import AttemptOutcome, JobStatus, RunStatus
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    CaseResult,
    EvaluationJob,
    EvaluationRun,
    JobAttempt,
    ProductExperiment,
)
from app.runs.idempotency import canonical_request_hash


class ResultSnapshotIntegrityError(ValueError):
    """Stored identities cannot support an honest final result snapshot."""


class ExperimentNotTerminalError(ValueError):
    """An experiment is still executing; its final result set cannot be exported yet."""


def freeze_durable_job(
    job: EvaluationJob, result: CaseResult | None, attempt: JobAttempt | None
) -> dict[str, Any]:
    if job.status not in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
        raise ExperimentNotTerminalError("experiment jobs are not terminal")
    frozen: dict[str, Any] = {
        "job_id": str(job.id),
        "run_id": str(job.run_id),
        "case_id": job.case_id,
        "job_status": job.status.value,
        "job_version": job.version,
        "attempt_count": job.attempt_count,
        "result_id": None,
        "accepted_attempt_id": None,
        "accepted_attempt_number": None,
        "accepted_started_at": None,
        "accepted_finished_at": None,
        "metrics": None,
        "error_code": job.last_error_code if job.status == JobStatus.FAILED else None,
    }
    if job.status != JobStatus.SUCCEEDED:
        if result is not None or attempt is not None:
            raise ResultSnapshotIntegrityError("non-success job contains a success result")
        return frozen
    if (
        result is None
        or attempt is None
        or result.accepted_attempt_id is None
        or (result.job_id, result.run_id, result.case_id) != (job.id, job.run_id, job.case_id)
        or (attempt.id, attempt.job_id) != (result.accepted_attempt_id, job.id)
        or attempt.attempt_number != job.attempt_count
        or attempt.outcome != AttemptOutcome.SUCCEEDED
        or attempt.started_at is None
        or attempt.finished_at is None
        or attempt.finished_at < attempt.started_at
    ):
        raise ResultSnapshotIntegrityError("success result has no matching accepted attempt")
    frozen.update(
        {
            "result_id": str(result.id),
            "accepted_attempt_id": str(attempt.id),
            "accepted_attempt_number": attempt.attempt_number,
            "accepted_started_at": attempt.started_at.isoformat(),
            "accepted_finished_at": attempt.finished_at.isoformat(),
            "metrics": deepcopy(result.metrics_json),
        }
    )
    return frozen


class SQLAlchemyProductResultReader:
    """Read a complete terminal pair in one MVCC snapshot; no locks or target calls.

    This is a detached point-in-time input for export, not yet a published immutable artifact.
    """

    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def read(self, *, tenant_id: UUID, experiment_id: UUID) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            # First statement, before any identity/state/result reads. No write is permitted.
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            experiment = await session.scalar(
                select(ProductExperiment).where(
                    ProductExperiment.id == experiment_id,
                    ProductExperiment.tenant_id == tenant_id,
                )
            )
            if experiment is None:
                return None
            run_ids = (experiment.baseline_run_id, experiment.candidate_run_id)
            runs = {
                run.id: run
                for run in (
                    await session.scalars(
                        select(EvaluationRun).where(
                            EvaluationRun.id.in_(run_ids), EvaluationRun.tenant_id == tenant_id
                        )
                    )
                ).all()
            }
            if len(runs) != 2 or any(
                run.product_experiment_id != experiment.id for run in runs.values()
            ):
                raise ResultSnapshotIntegrityError("experiment run identities are inconsistent")
            terminal = {
                RunStatus.SUCCEEDED,
                RunStatus.PARTIALLY_SUCCEEDED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
            }
            if any(run.status not in terminal for run in runs.values()):
                raise ExperimentNotTerminalError("experiment runs are not terminal")
            if any(not 2 <= run.total_jobs <= 10000 for run in runs.values()):
                raise ResultSnapshotIntegrityError("experiment job count is outside export limits")
            snapshot = deepcopy(experiment.snapshot_json)
            unsigned = dict(snapshot)
            digest = unsigned.pop("content_sha256", None)
            if digest != canonical_request_hash(unsigned):
                raise ResultSnapshotIntegrityError("experiment input snapshot hash mismatch")
            statement = (
                select(EvaluationJob, CaseResult, JobAttempt)
                .outerjoin(CaseResult, CaseResult.job_id == EvaluationJob.id)
                .outerjoin(JobAttempt, JobAttempt.id == CaseResult.accepted_attempt_id)
                .where(EvaluationJob.run_id.in_(run_ids))
                .order_by(EvaluationJob.run_id, EvaluationJob.case_id)
                .limit(20001)
                .options(
                    load_only(
                        EvaluationJob.id,
                        EvaluationJob.run_id,
                        EvaluationJob.case_id,
                        EvaluationJob.status,
                        EvaluationJob.version,
                        EvaluationJob.attempt_count,
                        EvaluationJob.last_error_code,
                    ),
                    load_only(
                        CaseResult.id,
                        CaseResult.job_id,
                        CaseResult.run_id,
                        CaseResult.tenant_id,
                        CaseResult.case_id,
                        CaseResult.accepted_attempt_id,
                        CaseResult.metrics_json,
                    ),
                    load_only(
                        JobAttempt.id,
                        JobAttempt.job_id,
                        JobAttempt.attempt_number,
                        JobAttempt.outcome,
                        JobAttempt.started_at,
                        JobAttempt.finished_at,
                    ),
                )
            )
            jobs: dict[UUID, list[dict[str, Any]]] = {run_id: [] for run_id in run_ids}
            for job, result, attempt in (await session.execute(statement)).all():
                if result is not None and result.tenant_id != tenant_id:
                    raise ResultSnapshotIntegrityError("result ownership mismatch")
                jobs[job.run_id].append(freeze_durable_job(job, result, attempt))
            for run in runs.values():
                outcomes = jobs[run.id]
                counts = tuple(
                    sum(row["job_status"] == state.value for row in outcomes)
                    for state in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)
                )
                if len(outcomes) != run.total_jobs or counts != (
                    run.succeeded_jobs,
                    run.failed_jobs,
                    run.cancelled_jobs,
                ):
                    raise ResultSnapshotIntegrityError("terminal job coverage or counters mismatch")
            if [row["case_id"] for row in jobs[run_ids[0]]] != [
                row["case_id"] for row in jobs[run_ids[1]]
            ]:
                raise ResultSnapshotIntegrityError("experiment arms do not cover the same cases")
            frozen: dict[str, Any] = {
                "schema_version": "evalops.durable-result-snapshot/1.0",
                "experiment_id": str(experiment.id),
                "tenant_id": str(tenant_id),
                "request_sha256": experiment.request_hash,
                "input_snapshot": snapshot,
                "source_artifact_reference_id": (
                    str(experiment.source_artifact_reference_id)
                    if experiment.source_artifact_reference_id is not None
                    else None
                ),
                "arms": {
                    label: {
                        "run_id": str(run_id),
                        "run_version": runs[run_id].version,
                        "run_status": runs[run_id].status.value,
                        "dataset_version_id": str(runs[run_id].dataset_version_id),
                        "dataset_sha256": runs[run_id].dataset_hash,
                        "target_config_sha256": runs[run_id].target_config_hash,
                        "evaluator_config_sha256": runs[run_id].evaluator_config_hash,
                        "target_version": runs[run_id].target_version,
                        "evaluator_version": runs[run_id].evaluator_version,
                        "jobs": jobs[run_id],
                    }
                    for label, run_id in zip(("baseline", "candidate"), run_ids, strict=True)
                },
                "formal_quality_claim_allowed": False,
                "production_ready": False,
            }
            frozen["content_sha256"] = canonical_request_hash(frozen)
            return frozen
