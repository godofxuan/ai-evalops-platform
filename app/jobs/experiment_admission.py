"""Shared database-active-claim admission for managed pairs, not a second scheduler."""

from typing import Any

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.enums import JobStatus, RunStatus
from app.persistence.orm_models import EvaluationJob, EvaluationRun, ProductExperiment

ACTIVE_CLAIM_STATES = (JobStatus.RUNNING, JobStatus.CANCELLING)


def experiment_capacity_available() -> Any:
    """Read-only eligibility hint. Admission MUST recheck under the parent lock."""
    active = aliased(EvaluationJob, name="experiment_active_jobs")
    active_count = (
        select(func.count(active.id))
        .where(
            active.run_id.in_(
                (ProductExperiment.baseline_run_id, ProductExperiment.candidate_run_id)
            ),
            active.status.in_(ACTIVE_CLAIM_STATES),
        )
        .correlate(ProductExperiment)
        .scalar_subquery()
    )
    available = (
        select(ProductExperiment.id)
        .where(
            ProductExperiment.id == EvaluationRun.product_experiment_id,
            ProductExperiment.tenant_id == EvaluationRun.tenant_id,
            EvaluationRun.id.in_(
                (ProductExperiment.baseline_run_id, ProductExperiment.candidate_run_id)
            ),
            ProductExperiment.cancel_requested.is_(False),
            active_count < ProductExperiment.max_active_jobs,
        )
        .correlate(EvaluationRun)
    )
    return or_(EvaluationRun.product_experiment_id.is_(None), exists(available))


async def admit_experiment_claim(session: AsyncSession, run: EvaluationRun) -> bool:
    """Called before any Job/attempt mutation in the existing claim transaction.

    The Job is already locked: never wait for the Experiment or Run in reverse
    cancellation order. SKIP LOCKED yields the Job back when either is busy.
    Expired/CANCELLING claims retain capacity until the existing state machine
    releases them. This is not a physical upstream-call concurrency guarantee.
    """
    if run.product_experiment_id is None:
        return True
    parent = await session.scalar(
        select(ProductExperiment)
        .where(
            ProductExperiment.id == run.product_experiment_id,
            ProductExperiment.tenant_id == run.tenant_id,
        )
        .with_for_update(of=ProductExperiment, skip_locked=True)
    )
    if parent is None or parent.cancel_requested or parent.max_active_jobs is None:
        return False
    run_ids = (parent.baseline_run_id, parent.candidate_run_id)
    if run.id not in run_ids:
        return False
    refreshed = await session.scalar(
        select(EvaluationRun)
        .where(EvaluationRun.id == run.id, EvaluationRun.tenant_id == run.tenant_id)
        .with_for_update(of=EvaluationRun, key_share=True, skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if refreshed is None or refreshed.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
        return False
    active_count = await session.scalar(
        select(func.count(EvaluationJob.id)).where(
            EvaluationJob.run_id.in_(run_ids), EvaluationJob.status.in_(ACTIVE_CLAIM_STATES)
        )
    )
    return active_count is not None and active_count < parent.max_active_jobs
