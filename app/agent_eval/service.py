"""Tenant-scoped ingestion for immutable Agent execution artifacts."""

from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_eval.schema import (
    ArtifactSchemaVersion,
    artifact_content_sha256,
    canonical_artifact_bytes,
)
from app.agent_eval.schemas import AgentArtifactRead, AgentArtifactUpload
from app.artifacts.repository import ensure_artifact_reference
from app.artifacts.storage import ArtifactStore
from app.auth.principals import Principal
from app.domain.enums import ArtifactType
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    AgentExecutionArtifact,
    AuditEvent,
    EvaluationJob,
    EvaluationRun,
)
from app.runs.service import RunNotFoundError


class AgentArtifactRunMismatchError(ValueError):
    """The producer artifact does not belong to the URL Run or one of its cases."""


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
