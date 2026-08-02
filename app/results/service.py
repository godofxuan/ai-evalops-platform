import json
from typing import Any, Protocol
from typing import cast as type_cast
from uuid import UUID

from sqlalchemy import Float, Select, and_, case, cast, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.artifacts.repository import ensure_artifact_reference
from app.artifacts.storage import ArtifactStore, StoredArtifact
from app.auth.principals import Principal
from app.domain.enums import ArtifactType, JobStatus
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    ArtifactReference,
    CaseResult,
    EvaluationJob,
    EvaluationRun,
    RunMetric,
)
from app.results.comparison import (
    ComparableCase,
    ComparableRun,
    RunComparison,
)
from app.results.comparison import (
    compare_runs as compare_run_values,
)
from app.results.cursor import CursorCodec, PagePosition
from app.results.metrics import CaseOutcome, MetricsSummary, aggregate_metrics
from app.results.schemas import (
    ArtifactRead,
    CasePage,
    CaseQuery,
    CaseRead,
    ChangedCaseRead,
    DistributionRead,
    MetricsRead,
    RunComparisonRead,
)
from app.runs.service import RunNotFoundError


class ResultService(Protocol):
    async def list_cases(
        self,
        *,
        principal: Principal,
        run_id: UUID,
        query: CaseQuery,
    ) -> CasePage:
        """List tenant-owned Run cases using an opaque keyset cursor."""

    async def get_metrics(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> MetricsRead:
        """Recompute and persist aggregate metrics from durable case state."""

    async def compare_runs(
        self,
        *,
        principal: Principal,
        left_run_id: UUID,
        right_run_id: UUID,
    ) -> RunComparisonRead:
        """Compare two tenant-owned Runs and expose dataset mismatch boundaries."""

    async def generate_artifacts(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> list[ArtifactRead]:
        """Generate deterministic JSON reports and persist tenant/run metadata."""


def build_case_page_statement(
    *,
    tenant_id: UUID,
    run_id: UUID,
    query: CaseQuery,
    position: PagePosition | None,
) -> tuple[Select[Any], ColumnElement[Any]]:
    sort_expression = _sort_expression(query)
    statement = (
        select(
            EvaluationJob,
            CaseResult,
            sort_expression.label("_sort_value"),
        )
        .join(EvaluationRun, EvaluationRun.id == EvaluationJob.run_id)
        .outerjoin(CaseResult, CaseResult.job_id == EvaluationJob.id)
        .where(
            EvaluationRun.tenant_id == tenant_id,
            EvaluationJob.run_id == run_id,
        )
    )
    if query.status is not None:
        statement = statement.where(EvaluationJob.status == query.status)
    if query.error_code is not None:
        statement = statement.where(EvaluationJob.last_error_code == query.error_code)
    if position is not None:
        statement = statement.where(
            _keyset_condition(
                sort_expression=sort_expression,
                position=position,
                direction=query.direction,
            )
        )
    ordered = (
        sort_expression.asc().nulls_last()
        if query.direction == "asc"
        else sort_expression.desc().nulls_last()
    )
    return (
        statement.order_by(ordered, EvaluationJob.id.asc()).limit(query.limit + 1),
        sort_expression,
    )


class SQLAlchemyResultService:
    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        *,
        cursor_codec: CursorCodec | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._cursor_codec = cursor_codec or CursorCodec()
        self._artifact_store = artifact_store

    async def list_cases(
        self,
        *,
        principal: Principal,
        run_id: UUID,
        query: CaseQuery,
    ) -> CasePage:
        position = (
            None if query.cursor is None else self._cursor_codec.decode(query.cursor, query=query)
        )
        statement, _ = build_case_page_statement(
            tenant_id=principal.tenant_id,
            run_id=run_id,
            query=query,
            position=position,
        )
        async with self._session_factory() as session:
            run_exists = await session.scalar(
                select(EvaluationRun.id).where(
                    EvaluationRun.id == run_id,
                    EvaluationRun.tenant_id == principal.tenant_id,
                )
            )
            if run_exists is None:
                raise RunNotFoundError
            rows = (await session.execute(statement)).all()
        has_more = len(rows) > query.limit
        visible_rows = rows[: query.limit]
        items = [
            CaseRead(
                job_id=job.id,
                case_id=job.case_id,
                status=job.status,
                attempt_count=job.attempt_count,
                error_code=job.last_error_code,
                answer=None if result is None else result.answer_json,
                evidence={} if result is None else result.evidence_json,
                metrics={} if result is None else result.metrics_json,
                latency_ms=None if result is None else result.latency_ms,
                finished_at=job.finished_at,
            )
            for job, result, _sort_value in visible_rows
        ]
        next_cursor = None
        if has_more and visible_rows:
            last_job, _last_result, last_value = visible_rows[-1]
            next_cursor = self._cursor_codec.encode(
                PagePosition(
                    value=_position_value(last_value, query=query),
                    job_id=last_job.id,
                ),
                query=query,
            )
        return CasePage(items=items, next_cursor=next_cursor)

    async def get_metrics(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> MetricsRead:
        async with self._session_factory.begin() as session:
            run_exists = await session.scalar(
                select(EvaluationRun.id).where(
                    EvaluationRun.id == run_id,
                    EvaluationRun.tenant_id == principal.tenant_id,
                )
            )
            if run_exists is None:
                raise RunNotFoundError
            rows = (
                await session.execute(
                    select(
                        EvaluationJob.status,
                        CaseResult.latency_ms,
                        CaseResult.metrics_json,
                    )
                    .outerjoin(CaseResult, CaseResult.job_id == EvaluationJob.id)
                    .where(EvaluationJob.run_id == run_id)
                )
            ).all()
            summary = aggregate_metrics(
                [
                    CaseOutcome(
                        status=status,
                        latency_ms=latency_ms,
                        metrics={} if metrics is None else dict(metrics),
                    )
                    for status, latency_ms, metrics in rows
                ]
            )
            await _replace_run_metrics(session, run_id=run_id, summary=summary)
        return _metrics_read(summary)

    async def compare_runs(
        self,
        *,
        principal: Principal,
        left_run_id: UUID,
        right_run_id: UUID,
    ) -> RunComparisonRead:
        async with self._session_factory() as session:
            left = await _load_comparable_run(
                session,
                tenant_id=principal.tenant_id,
                run_id=left_run_id,
            )
            right = await _load_comparable_run(
                session,
                tenant_id=principal.tenant_id,
                run_id=right_run_id,
            )
        return _comparison_read(compare_run_values(left, right))

    async def generate_artifacts(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> list[ArtifactRead]:
        if self._artifact_store is None:
            raise RuntimeError("artifact store is not configured")
        async with self._session_factory() as session:
            run = (
                await session.execute(
                    select(EvaluationRun).where(
                        EvaluationRun.id == run_id,
                        EvaluationRun.tenant_id == principal.tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if run is None:
                raise RunNotFoundError
            rows = (
                await session.execute(
                    select(EvaluationJob, CaseResult)
                    .outerjoin(CaseResult, CaseResult.job_id == EvaluationJob.id)
                    .where(EvaluationJob.run_id == run_id)
                    .order_by(EvaluationJob.case_id.asc())
                )
            ).all()
        summary = aggregate_metrics(
            [
                CaseOutcome(
                    job.status,
                    None if result is None else result.latency_ms,
                    {} if result is None else dict(result.metrics_json),
                )
                for job, result in rows
            ]
        )
        metrics = _metrics_read(summary)
        failures = [
            {
                "case_id": job.case_id,
                "status": job.status.value,
                "error_code": job.last_error_code,
            }
            for job, _result in rows
            if job.status in {JobStatus.FAILED, JobStatus.CANCELLED}
        ]
        payloads: dict[ArtifactType, dict[str, Any]] = {
            ArtifactType.RUN_METRICS: {
                "schema_version": "1",
                "run_id": str(run_id),
                "metrics": metrics.model_dump(mode="json"),
            },
            ArtifactType.FAILURE_CASES: {
                "schema_version": "1",
                "run_id": str(run_id),
                "failures": failures,
            },
            ArtifactType.SUMMARY_REPORT: {
                "schema_version": "1",
                "run_id": str(run_id),
                "dataset_version_id": str(run.dataset_version_id),
                "run_status": run.status.value,
                "target_version": run.target_version,
                "evaluator_version": run.evaluator_version,
                "metrics": metrics.model_dump(mode="json"),
                "failure_count": len(failures),
            },
        }
        stored = {
            artifact_type: await self._artifact_store.put_bytes(_json_bytes(payload))
            for artifact_type, payload in payloads.items()
        }
        artifacts: list[tuple[ArtifactReference, StoredArtifact]] = []
        async with self._session_factory.begin() as session:
            await _replace_run_metrics(session, run_id=run_id, summary=summary)
            for artifact_type, item in stored.items():
                artifacts.append(
                    (
                        await ensure_artifact_reference(
                            session,
                            tenant_id=principal.tenant_id,
                            run_id=run_id,
                            artifact_type=artifact_type,
                            media_type="application/json",
                            stored=item,
                        ),
                        item,
                    )
                )
        return [
            ArtifactRead(
                id=reference.id,
                run_id=run_id,
                artifact_type=reference.artifact_type,
                sha256=item.sha256,
                media_type=reference.media_type,
                byte_size=item.size_bytes,
                created_at=reference.created_at,
            )
            for reference, item in artifacts
        ]


def _sort_expression(query: CaseQuery) -> ColumnElement[Any]:
    if query.sort == "case_id":
        return type_cast(ColumnElement[Any], EvaluationJob.case_id)
    if query.sort == "latency":
        return type_cast(ColumnElement[Any], CaseResult.latency_ms)
    assert query.metric_name is not None
    metric_value = CaseResult.metrics_json[query.metric_name]
    return case(
        (
            func.jsonb_typeof(metric_value) == "number",
            cast(metric_value.astext, Float),
        ),
        else_=None,
    )


def _keyset_condition(
    *,
    sort_expression: ColumnElement[Any],
    position: PagePosition,
    direction: str,
) -> ColumnElement[bool]:
    if position.value is None:
        return and_(
            sort_expression.is_(None),
            EvaluationJob.id > position.job_id,
        )
    beyond = (
        sort_expression > position.value if direction == "asc" else sort_expression < position.value
    )
    return or_(
        beyond,
        and_(
            sort_expression == position.value,
            EvaluationJob.id > position.job_id,
        ),
        sort_expression.is_(None),
    )


def _position_value(value: object, *, query: CaseQuery) -> str | float | None:
    if value is None:
        return None
    if query.sort == "case_id":
        return str(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("numeric sort expression returned a nonnumeric value")
    return float(value)


def _metrics_read(summary: MetricsSummary) -> MetricsRead:
    return MetricsRead(
        total_jobs=summary.total_jobs,
        completion_rate=summary.completion_rate,
        success_rate=summary.success_rate,
        failure_rate=summary.failure_rate,
        cancellation_rate=summary.cancellation_rate,
        latency=DistributionRead(
            count=summary.latency.count,
            mean=summary.latency.mean,
            p50=summary.latency.p50,
            p95=summary.latency.p95,
        ),
        evaluator_metrics={
            name: DistributionRead(
                count=distribution.count,
                mean=distribution.mean,
                p50=distribution.p50,
                p95=distribution.p95,
            )
            for name, distribution in summary.evaluator_metrics.items()
        },
    )


def _metric_rows(
    summary: MetricsSummary,
) -> list[tuple[str, float | None, dict[str, Any]]]:
    rows: list[tuple[str, float | None, dict[str, Any]]] = [
        ("completion_rate", summary.completion_rate, {}),
        ("success_rate", summary.success_rate, {}),
        ("failure_rate", summary.failure_rate, {}),
        ("cancellation_rate", summary.cancellation_rate, {}),
        ("latency.mean_ms", summary.latency.mean, {"count": summary.latency.count}),
        ("latency.p50_ms", summary.latency.p50, {"count": summary.latency.count}),
        ("latency.p95_ms", summary.latency.p95, {"count": summary.latency.count}),
    ]
    rows.extend(
        (
            f"evaluator.{name}",
            distribution.mean,
            {
                "count": distribution.count,
                "p50": distribution.p50,
                "p95": distribution.p95,
            },
        )
        for name, distribution in summary.evaluator_metrics.items()
    )
    return rows


async def _replace_run_metrics(
    session: AsyncSession,
    *,
    run_id: UUID,
    summary: MetricsSummary,
) -> None:
    await session.execute(delete(RunMetric).where(RunMetric.run_id == run_id))
    for name, value, details in _metric_rows(summary):
        session.add(
            RunMetric(
                run_id=run_id,
                metric_name=name,
                metric_value=value,
                metric_json=details,
            )
        )


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


async def _load_comparable_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    run_id: UUID,
) -> ComparableRun:
    run = (
        await session.execute(
            select(EvaluationRun).where(
                EvaluationRun.id == run_id,
                EvaluationRun.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise RunNotFoundError
    rows = (
        await session.execute(
            select(EvaluationJob, CaseResult)
            .outerjoin(CaseResult, CaseResult.job_id == EvaluationJob.id)
            .where(EvaluationJob.run_id == run_id)
        )
    ).all()
    return ComparableRun(
        dataset_version_id=run.dataset_version_id,
        cases={
            job.case_id: ComparableCase(
                status=job.status,
                latency_ms=None if result is None else result.latency_ms,
                metrics={} if result is None else dict(result.metrics_json),
            )
            for job, result in rows
        },
    )


def _comparison_read(comparison: RunComparison) -> RunComparisonRead:
    return RunComparisonRead(
        warning=comparison.warning,
        intersection_count=comparison.intersection_count,
        left_only_count=comparison.left_only_count,
        right_only_count=comparison.right_only_count,
        left=_metrics_read(comparison.left_summary),
        right=_metrics_read(comparison.right_summary),
        metric_deltas=comparison.metric_deltas,
        only_left_failed=list(comparison.only_left_failed),
        only_right_failed=list(comparison.only_right_failed),
        changed_cases=[
            ChangedCaseRead(
                case_id=item.case_id,
                metric_deltas=item.metric_deltas,
                latency_delta_ms=item.latency_delta_ms,
            )
            for item in comparison.changed_cases
        ],
    )
