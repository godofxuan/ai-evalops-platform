"""Fail-closed stdio entry point with per-call database authorization."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from app.agent_eval.control_plane import McpEvalControlPlane
from app.agent_eval.mcp_server import build_mcp_server
from app.agent_eval.mcp_service_adapter import EvalOpsMcpServiceAdapter
from app.agent_eval.regression_service import SQLAlchemyAgentRegressionService
from app.agent_eval.service import SQLAlchemyAgentArtifactService
from app.artifacts.storage import build_artifact_store
from app.auth.api_keys import verify_api_key
from app.auth.principals import Principal
from app.auth.repository import SQLAlchemyAPIKeyLookup
from app.auth.service import InvalidAPIKeyError, authenticate_api_key
from app.core.config import Settings
from app.core.event_loop import run_with_psycopg_compatible_event_loop
from app.core.telemetry import Telemetry, parse_otlp_headers
from app.domain.enums import APIKeyStatus, TenantStatus
from app.persistence.database import (
    AsyncSessionFactory,
    create_database_engine,
    create_session_factory,
)
from app.persistence.orm_models import APIKey, AuditEvent, McpAuditOutbox, Tenant
from app.results.service import SQLAlchemyResultService
from app.runs.repository import SQLAlchemyRunRepository
from app.runs.service import SQLAlchemyRunService


def configured_mcp_api_key(settings: Settings) -> str:
    if settings.mcp_api_key is None:
        raise RuntimeError("EVALOPS_MCP_API_KEY is required for the MCP stdio server")
    return settings.mcp_api_key.get_secret_value()


class SQLAlchemyMcpCallAuthorizer:
    """Hold shared credential/tenant locks across one service-layer call."""

    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        *,
        plaintext_api_key: str,
        credential_identity: Principal,
    ) -> None:
        self._session_factory = session_factory
        self._plaintext_api_key = plaintext_api_key
        self._credential_identity = credential_identity

    def authorize(self, *, tool_name: str) -> AbstractAsyncContextManager[Principal]:
        del tool_name
        return self._authorize()

    @asynccontextmanager
    async def _authorize(self) -> AsyncIterator[Principal]:
        session_factory = self._session_factory
        async with session_factory.begin() as session:
            row = (
                await session.execute(
                    select(APIKey, Tenant.status)
                    .join(Tenant, Tenant.id == APIKey.tenant_id)
                    .where(APIKey.id == self._credential_identity.api_key_id)
                    .with_for_update(read=True)
                )
            ).one_or_none()
            if row is None:
                raise InvalidAPIKeyError
            api_key, tenant_status = row
            now = datetime.now(UTC)
            hash_matches = await asyncio.to_thread(
                verify_api_key,
                self._plaintext_api_key,
                api_key.key_hash,
            )
            if (
                not hash_matches
                or api_key.status is not APIKeyStatus.ACTIVE
                or (api_key.expires_at is not None and api_key.expires_at <= now)
                or tenant_status is not TenantStatus.ACTIVE
            ):
                raise InvalidAPIKeyError
            api_key.last_used_at = now
            yield Principal(
                tenant_id=api_key.tenant_id,
                api_key_id=api_key.id,
                key_prefix=api_key.key_prefix,
                can_review=api_key.can_review,
                can_create_review_tasks=api_key.can_create_review_tasks,
            )


class SQLAlchemyMcpCallAuditor:
    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def reserve(
        self,
        *,
        principal: Principal,
        tool_name: str,
        call_identity: str,
        trace_id: str,
    ) -> None:
        async with self._session_factory.begin() as session:
            await session.execute(
                postgresql_insert(McpAuditOutbox)
                .values(
                    tenant_id=principal.tenant_id,
                    api_key_id=principal.api_key_id,
                    tool_name=tool_name,
                    call_identity=call_identity,
                    trace_id=trace_id,
                )
                .on_conflict_do_nothing(constraint="uq_mcp_audit_outbox_call_identity")
            )
            row = (
                await session.execute(
                    select(McpAuditOutbox).where(
                        McpAuditOutbox.tenant_id == principal.tenant_id,
                        McpAuditOutbox.tool_name == tool_name,
                        McpAuditOutbox.call_identity == call_identity,
                    )
                )
            ).scalar_one()
            if row.api_key_id != principal.api_key_id or row.trace_id != trace_id:
                raise RuntimeError("MCP audit call identity conflicts with prior reservation")

    async def record(
        self,
        *,
        principal: Principal,
        tool_name: str,
        status: str,
        trace_id: str,
    ) -> None:
        async with self._session_factory.begin() as session:
            row = (
                await session.execute(
                    select(McpAuditOutbox)
                    .where(
                        McpAuditOutbox.tenant_id == principal.tenant_id,
                        McpAuditOutbox.tool_name == tool_name,
                        McpAuditOutbox.trace_id == trace_id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            if row.delivery_status == "DELIVERED":
                return
            row.outcome_status = status
            row.attempt_count += 1
        await self._deliver(principal=principal, trace_id=trace_id)

    async def retry_pending(self, *, principal: Principal, limit: int = 100) -> int:
        async with self._session_factory() as session:
            trace_ids = tuple(
                await session.scalars(
                    select(McpAuditOutbox.trace_id)
                    .where(
                        McpAuditOutbox.tenant_id == principal.tenant_id,
                        McpAuditOutbox.api_key_id == principal.api_key_id,
                        McpAuditOutbox.delivery_status == "PENDING",
                        McpAuditOutbox.outcome_status.is_not(None),
                    )
                    .order_by(McpAuditOutbox.created_at, McpAuditOutbox.id)
                    .limit(limit)
                )
            )
        delivered = 0
        for trace_id in trace_ids:
            await self._deliver(principal=principal, trace_id=trace_id)
            delivered += 1
        return delivered

    async def _deliver(self, *, principal: Principal, trace_id: str) -> None:
        async with self._session_factory.begin() as session:
            row = (
                await session.execute(
                    select(McpAuditOutbox)
                    .where(
                        McpAuditOutbox.tenant_id == principal.tenant_id,
                        McpAuditOutbox.api_key_id == principal.api_key_id,
                        McpAuditOutbox.trace_id == trace_id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            if row.delivery_status == "DELIVERED":
                return
            if row.outcome_status is None:
                raise RuntimeError("MCP audit outcome is not durable")
            session.add(
                AuditEvent(
                    tenant_id=principal.tenant_id,
                    actor_id=str(principal.api_key_id),
                    action="mcp.tool_called",
                    resource_type="mcp_audit_outbox",
                    resource_id=row.id,
                    metadata_json={
                        "api_key_id": str(principal.api_key_id),
                        "tool_name": row.tool_name,
                        "status": row.outcome_status,
                        "trace_id": trace_id,
                        "delivery_attempt": row.attempt_count,
                    },
                )
            )
            row.delivery_status = "DELIVERED"
            row.delivered_at = datetime.now(UTC)
            row.last_error_code = None


async def run_stdio(settings: Settings | None = None) -> None:
    runtime_settings = settings or Settings()
    plaintext_api_key = configured_mcp_api_key(runtime_settings)
    engine = create_database_engine(runtime_settings)
    session_factory = create_session_factory(engine)
    artifact_store = build_artifact_store(runtime_settings)
    telemetry = Telemetry(
        service_name=runtime_settings.otel_service_name,
        enabled=runtime_settings.otel_enabled,
        otlp_endpoint=runtime_settings.otel_exporter_otlp_endpoint,
        otlp_headers=parse_otlp_headers(
            None
            if runtime_settings.otel_exporter_otlp_headers is None
            else runtime_settings.otel_exporter_otlp_headers.get_secret_value()
        ),
        resource_attributes={"process.role": "mcp-stdio"},
    )
    try:
        principal = await authenticate_api_key(
            plaintext_api_key,
            lookup=SQLAlchemyAPIKeyLookup(session_factory),
            now=datetime.now(UTC),
        )
        run_service = SQLAlchemyRunService(
            repository=SQLAlchemyRunRepository(session_factory),
            artifact_store=artifact_store,
            http_target_registry=runtime_settings.http_target_registry,
            telemetry=telemetry,
        )
        result_service = SQLAlchemyResultService(
            session_factory,
            artifact_store=artifact_store,
        )
        agent_artifact_service = SQLAlchemyAgentArtifactService(
            session_factory,
            artifact_store=artifact_store,
        )
        agent_regression_service = SQLAlchemyAgentRegressionService(session_factory)
        services = EvalOpsMcpServiceAdapter(
            run_service=run_service,
            result_service=result_service,
            agent_artifact_service=agent_artifact_service,
            agent_regression_service=agent_regression_service,
        )
        auditor = SQLAlchemyMcpCallAuditor(session_factory)
        await auditor.retry_pending(principal=principal)
        server = build_mcp_server(
            control_plane=McpEvalControlPlane(services=services),
            authorizer=SQLAlchemyMcpCallAuthorizer(
                session_factory,
                plaintext_api_key=plaintext_api_key,
                credential_identity=principal,
            ),
            auditor=auditor,
            credential_identity=principal,
        )
        await server.run_stdio_async()
    finally:
        await engine.dispose()
        telemetry.shutdown()


def main() -> None:
    run_with_psycopg_compatible_event_loop(run_stdio())


if __name__ == "__main__":
    main()
