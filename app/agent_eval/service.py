"""Tenant-scoped ingestion and evaluation of immutable Agent execution artifacts."""

import hashlib
import json
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_eval.evaluators import build_agent_evaluator, registered_agent_evaluators
from app.agent_eval.failure_taxonomy import classify_agent_failure
from app.agent_eval.schema import (
    AgentRunArtifact,
    ArtifactSchemaVersion,
    artifact_content_sha256,
    canonical_artifact_bytes,
)
from app.agent_eval.schemas import (
    AgentArtifactDetailRead,
    AgentArtifactEvaluationRequest,
    AgentArtifactEvaluationResultRead,
    AgentArtifactRead,
    AgentArtifactUpload,
    AgentEvaluatorKind,
)
from app.artifacts.repository import ensure_artifact_reference
from app.artifacts.storage import ArtifactStore
from app.auth.principals import Principal
from app.domain.enums import ArtifactType
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    AgentEvaluationResultRecord,
    AgentExecutionArtifact,
    AuditEvent,
    EvaluationJob,
    EvaluationRun,
)
from app.runs.service import RunNotFoundError


class AgentArtifactRunMismatchError(ValueError):
    """The producer artifact does not belong to the URL Run or one of its cases."""


class AgentArtifactNotFoundError(Exception):
    """No artifact exists for the authenticated tenant and requested Run."""


class SQLAlchemyAgentArtifactService:
    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        *,
        artifact_store: ArtifactStore,
    ) -> None:
        self._session_factory = session_factory
        self._artifact_store = artifact_store

    async def ingest(
        self,
        *,
        principal: Principal,
        run_id: UUID,
        request: AgentArtifactUpload,
    ) -> AgentArtifactRead:
        artifact = request.artifact
        if artifact.run_id != str(run_id):
            raise AgentArtifactRunMismatchError("artifact run_id does not match the URL Run")

        # Validate authorization and case ownership before an object-store side effect.
        await self._require_owned_job(
            tenant_id=principal.tenant_id,
            run_id=run_id,
            case_id=artifact.case_id,
        )
        expected_sha256 = artifact_content_sha256(artifact)
        stored = await self._artifact_store.put_bytes(canonical_artifact_bytes(artifact))
        if stored.sha256 != expected_sha256:
            raise RuntimeError("artifact store returned an unexpected content digest")

        async with self._session_factory.begin() as session:
            job = await _owned_job(
                session,
                tenant_id=principal.tenant_id,
                run_id=run_id,
                case_id=artifact.case_id,
            )
            if job is None:
                raise RunNotFoundError
            reference = await ensure_artifact_reference(
                session,
                tenant_id=principal.tenant_id,
                run_id=run_id,
                artifact_type=ArtifactType.AGENT_EXECUTION,
                media_type="application/json",
                stored=stored,
            )
            inserted_id = await session.scalar(
                postgresql_insert(AgentExecutionArtifact)
                .values(
                    id=uuid4(),
                    tenant_id=principal.tenant_id,
                    run_id=run_id,
                    job_id=job.id,
                    case_id=artifact.case_id,
                    artifact_reference_id=reference.id,
                    content_sha256=stored.sha256,
                    schema_version=artifact.schema_version,
                    framework=artifact.framework,
                    session_id=artifact.session_id,
                    terminal_state=artifact.terminal.state,
                    usage_json=artifact.usage,
                    metadata_json=artifact.metadata,
                )
                .on_conflict_do_nothing(constraint="uq_agent_execution_artifacts_content_identity")
                .returning(AgentExecutionArtifact.id)
            )
            record = (
                await session.execute(
                    select(AgentExecutionArtifact).where(
                        AgentExecutionArtifact.id
                        == (
                            inserted_id
                            if inserted_id is not None
                            else select(AgentExecutionArtifact.id)
                            .where(
                                AgentExecutionArtifact.tenant_id == principal.tenant_id,
                                AgentExecutionArtifact.run_id == run_id,
                                AgentExecutionArtifact.case_id == artifact.case_id,
                                AgentExecutionArtifact.content_sha256 == stored.sha256,
                            )
                            .scalar_subquery()
                        )
                    )
                )
            ).scalar_one()
            if inserted_id is not None:
                session.add(
                    AuditEvent(
                        tenant_id=principal.tenant_id,
                        actor_id=str(principal.api_key_id),
                        action="agent_artifact.ingested",
                        resource_type="agent_execution_artifact",
                        resource_id=record.id,
                        metadata_json={
                            "run_id": str(run_id),
                            "case_id": artifact.case_id,
                            "content_sha256": stored.sha256,
                        },
                    )
                )
        return _read(record)

    async def evaluate(
        self,
        *,
        principal: Principal,
        run_id: UUID,
        artifact_id: UUID,
        request: AgentArtifactEvaluationRequest,
    ) -> list[AgentArtifactEvaluationResultRead]:
        metadata = await self._owned_artifact(
            tenant_id=principal.tenant_id,
            run_id=run_id,
            artifact_id=artifact_id,
        )
        if metadata is None:
            raise AgentArtifactNotFoundError

        content = await self._artifact_store.get_bytes(metadata.content_sha256)
        artifact = AgentRunArtifact.model_validate_json(content)
        if artifact_content_sha256(artifact) != metadata.content_sha256:
            raise RuntimeError("stored Agent artifact does not match its metadata digest")

        descriptors = {item.kind: item for item in registered_agent_evaluators()}
        computed: list[
            tuple[
                str,
                str,
                str,
                dict[str, object],
                dict[str, object],
                dict[str, str],
                list[str],
            ]
        ] = []
        for evaluator_kind in request.evaluators:
            config = request.config.get(evaluator_kind, {})
            config_sha256 = _configuration_sha256(config)
            descriptor = descriptors[evaluator_kind]
            evaluation = build_agent_evaluator(evaluator_kind, config).evaluate(artifact)
            metrics = evaluation.metrics
            category = classify_agent_failure(metrics)
            computed.append(
                (
                    evaluator_kind,
                    descriptor.implementation_version,
                    config_sha256,
                    config,
                    metrics,
                    evaluation.metric_provenance,
                    [] if category is None else [category.value],
                )
            )

        records: list[AgentEvaluationResultRecord] = []
        async with self._session_factory.begin() as session:
            still_owned = await session.scalar(
                select(AgentExecutionArtifact.id).where(
                    AgentExecutionArtifact.id == artifact_id,
                    AgentExecutionArtifact.tenant_id == principal.tenant_id,
                    AgentExecutionArtifact.run_id == run_id,
                )
            )
            if still_owned is None:
                raise AgentArtifactNotFoundError
            for (
                computed_kind,
                evaluator_version,
                config_sha256,
                config,
                metrics,
                metric_provenance,
                taxonomy,
            ) in computed:
                inserted_id = await session.scalar(
                    postgresql_insert(AgentEvaluationResultRecord)
                    .values(
                        id=uuid4(),
                        tenant_id=principal.tenant_id,
                        run_id=run_id,
                        artifact_id=artifact_id,
                        evaluator_kind=computed_kind,
                        evaluator_version=evaluator_version,
                        config_sha256=config_sha256,
                        config_json=config,
                        metrics_json=metrics,
                        metric_provenance_json=metric_provenance,
                        failure_taxonomy_json=taxonomy,
                    )
                    .on_conflict_do_nothing(constraint="uq_agent_eval_results_identity")
                    .returning(AgentEvaluationResultRecord.id)
                )
                predicate = (
                    AgentEvaluationResultRecord.artifact_id == artifact_id,
                    AgentEvaluationResultRecord.evaluator_kind == computed_kind,
                    AgentEvaluationResultRecord.evaluator_version == evaluator_version,
                    AgentEvaluationResultRecord.config_sha256 == config_sha256,
                )
                record = (
                    await session.execute(select(AgentEvaluationResultRecord).where(*predicate))
                ).scalar_one()
                records.append(record)
                if inserted_id is not None:
                    session.add(
                        AuditEvent(
                            tenant_id=principal.tenant_id,
                            actor_id=str(principal.api_key_id),
                            action="agent_artifact.evaluated",
                            resource_type="agent_evaluation_result",
                            resource_id=record.id,
                            metadata_json={
                                "run_id": str(run_id),
                                "artifact_id": str(artifact_id),
                                "evaluator_kind": computed_kind,
                                "evaluator_version": evaluator_version,
                                "config_sha256": config_sha256,
                            },
                        )
                    )
        return [_evaluation_read(record) for record in records]

    async def get(
        self,
        *,
        principal: Principal,
        run_id: UUID,
        artifact_id: UUID,
    ) -> AgentArtifactDetailRead:
        metadata = await self._owned_artifact(
            tenant_id=principal.tenant_id,
            run_id=run_id,
            artifact_id=artifact_id,
        )
        if metadata is None:
            raise AgentArtifactNotFoundError
        content = await self._artifact_store.get_bytes(metadata.content_sha256)
        artifact = AgentRunArtifact.model_validate_json(content)
        if artifact_content_sha256(artifact) != metadata.content_sha256:
            raise RuntimeError("stored Agent artifact does not match its metadata digest")
        return AgentArtifactDetailRead(
            id=metadata.id,
            content_sha256=metadata.content_sha256,
            artifact=artifact,
        )

    async def list_evaluations(
        self,
        *,
        principal: Principal,
        run_id: UUID,
        artifact_id: UUID,
    ) -> list[AgentArtifactEvaluationResultRead]:
        async with self._session_factory() as session:
            owned = await session.scalar(
                select(AgentExecutionArtifact.id).where(
                    AgentExecutionArtifact.id == artifact_id,
                    AgentExecutionArtifact.tenant_id == principal.tenant_id,
                    AgentExecutionArtifact.run_id == run_id,
                )
            )
            if owned is None:
                raise AgentArtifactNotFoundError
            records = (
                await session.execute(
                    select(AgentEvaluationResultRecord)
                    .where(
                        AgentEvaluationResultRecord.artifact_id == artifact_id,
                        AgentEvaluationResultRecord.tenant_id == principal.tenant_id,
                        AgentEvaluationResultRecord.run_id == run_id,
                    )
                    .order_by(
                        AgentEvaluationResultRecord.created_at,
                        AgentEvaluationResultRecord.evaluator_kind,
                    )
                )
            ).scalars()
            return [_evaluation_read(record) for record in records]

    async def _owned_artifact(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        artifact_id: UUID,
    ) -> AgentExecutionArtifact | None:
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(AgentExecutionArtifact).where(
                        AgentExecutionArtifact.id == artifact_id,
                        AgentExecutionArtifact.tenant_id == tenant_id,
                        AgentExecutionArtifact.run_id == run_id,
                    )
                )
            ).scalar_one_or_none()

    async def _require_owned_job(self, *, tenant_id: UUID, run_id: UUID, case_id: str) -> None:
        async with self._session_factory() as session:
            if (
                await _owned_job(session, tenant_id=tenant_id, run_id=run_id, case_id=case_id)
                is None
            ):
                raise RunNotFoundError


async def _owned_job(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    run_id: UUID,
    case_id: str,
) -> EvaluationJob | None:
    row = await session.execute(
        select(EvaluationJob)
        .join(EvaluationRun, EvaluationRun.id == EvaluationJob.run_id)
        .where(
            EvaluationRun.tenant_id == tenant_id,
            EvaluationJob.run_id == run_id,
            EvaluationJob.case_id == case_id,
        )
    )
    return row.scalar_one_or_none()


def _read(record: AgentExecutionArtifact) -> AgentArtifactRead:
    return AgentArtifactRead(
        id=record.id,
        run_id=record.run_id,
        case_id=record.case_id,
        schema_version=cast(ArtifactSchemaVersion, record.schema_version),
        framework=record.framework,
        content_sha256=record.content_sha256,
        terminal_state=record.terminal_state,
        created_at=record.created_at,
    )


def _configuration_sha256(config: dict[str, object]) -> str:
    canonical = json.dumps(
        config,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _evaluation_read(
    record: AgentEvaluationResultRecord,
) -> AgentArtifactEvaluationResultRead:
    return AgentArtifactEvaluationResultRead(
        id=record.id,
        artifact_id=record.artifact_id,
        evaluator_kind=cast(AgentEvaluatorKind, record.evaluator_kind),
        evaluator_version=record.evaluator_version,
        config_sha256=record.config_sha256,
        metrics=record.metrics_json,
        metric_provenance=record.metric_provenance_json,
        failure_taxonomy=record.failure_taxonomy_json,
        created_at=record.created_at,
    )
