import asyncio
import hashlib
import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.agent_eval.audit_dispatcher import (
    AuditDispatcher,
    SQLAlchemyAuditEventSink,
    SQLAlchemyAuditOutboxStore,
)
from app.auth.api_keys import generate_api_key
from app.core.config import Settings
from app.domain.enums import APIKeyStatus, ArtifactType, RunStatus
from app.persistence.database import create_database_engine, create_session_factory
from app.persistence.orm_models import (
    APIKey,
    ArtifactBlob,
    ArtifactReference,
    AuditEvent,
    Dataset,
    DatasetVersion,
    EvaluationRun,
    McpAuditOutbox,
    Tenant,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
async def test_real_stdio_mcp_revalidates_revocation_without_restart(
    tmp_path: Path,
) -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    tenant_id = uuid4()
    key_id = uuid4()
    dataset_id = uuid4()
    reference_id = uuid4()
    version_id = uuid4()
    run_id = uuid4()
    dataset_sha = hashlib.sha256(str(dataset_id).encode()).hexdigest()
    generated_key = generate_api_key()
    plaintext_key = generated_key.plaintext.get_secret_value()
    try:
        async with session_factory.begin() as session:
            session.add(Tenant(id=tenant_id, slug=f"mcp-{tenant_id.hex}", name="MCP test"))
            await session.flush()
            session.add_all(
                [
                    APIKey(
                        id=key_id,
                        tenant_id=tenant_id,
                        name="mcp-key",
                        key_prefix=generated_key.prefix,
                        key_hash=generated_key.key_hash,
                    ),
                    Dataset(id=dataset_id, tenant_id=tenant_id, name=f"mcp-{dataset_id.hex}"),
                    ArtifactBlob(
                        sha256=dataset_sha,
                        byte_size=1,
                        storage_path=f"{dataset_sha[:2]}/{dataset_sha}",
                    ),
                ]
            )
            await session.flush()
            session.add(
                ArtifactReference(
                    id=reference_id,
                    tenant_id=tenant_id,
                    artifact_type=ArtifactType.DATASET_SOURCE,
                    blob_sha256=dataset_sha,
                    media_type="application/x-ndjson",
                )
            )
            await session.flush()
            session.add(
                DatasetVersion(
                    id=version_id,
                    dataset_id=dataset_id,
                    tenant_id=tenant_id,
                    artifact_id=reference_id,
                    version=1,
                    schema_version="1",
                    sha256=dataset_sha,
                    case_count=1,
                )
            )
            await session.flush()
            session.add(
                EvaluationRun(
                    id=run_id,
                    tenant_id=tenant_id,
                    dataset_version_id=version_id,
                    dataset_hash=dataset_sha,
                    idempotency_key=f"mcp-{run_id}",
                    request_hash="a" * 64,
                    target_type="mock",
                    target_config_json={},
                    target_config_hash="b" * 64,
                    evaluator_type="basic_answer",
                    evaluator_config_json={},
                    evaluator_config_hash="c" * 64,
                    target_version="v1",
                    evaluator_version="v1",
                    status=RunStatus.SUCCEEDED,
                    total_jobs=0,
                    succeeded_jobs=0,
                    created_by=key_id,
                )
            )

        environment = dict(os.environ)
        environment.update(
            {
                "EVALOPS_DATABASE_URL": database_url,
                "EVALOPS_MCP_API_KEY": plaintext_key,
                "EVALOPS_ARTIFACT_ROOT": str(tmp_path / "artifacts"),
                "EVALOPS_OTEL_ENABLED": "false",
            }
        )
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.agent_eval.mcp_stdio"],
            env=environment,
            cwd=str(PROJECT_ROOT),
        )
        async with (
            stdio_client(parameters) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as client,
        ):
            await client.initialize()
            first = await client.call_tool("get_run_status", {"run_id": str(run_id)})
            assert first.is_error is False

            async with session_factory.begin() as session:
                key = await session.get(APIKey, key_id)
                assert key is not None
                key.status = APIKeyStatus.REVOKED

            second = await client.call_tool("get_run_status", {"run_id": str(run_id)})
            assert second.is_error is True

        async with session_factory() as session:
            audit_before_dispatch = (
                (await session.execute(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)))
                .scalars()
                .all()
            )
        assert audit_before_dispatch == []

        dispatcher = AuditDispatcher(
            store=SQLAlchemyAuditOutboxStore(
                session_factory,
                dispatcher_id="integration-system-dispatcher",
                lease_seconds=30,
            ),
            sink=SQLAlchemyAuditEventSink(session_factory),
            delivery_timeout_seconds=5,
            retry_base_seconds=1,
            retry_max_seconds=60,
        )
        dispatch_result = await dispatcher.dispatch_once(limit=100)
        assert dispatch_result.delivered == 2

        async with session_factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditEvent).where(
                            AuditEvent.tenant_id == tenant_id,
                            AuditEvent.action == "mcp.tool_called",
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert [row.metadata_json["status"] for row in audit_rows] == [
            "succeeded",
            "failed",
        ]
        assert all(row.resource_type == "mcp_tool" for row in audit_rows)
        assert all(row.resource_id == UUID(hex=row.metadata_json["trace_id"]) for row in audit_rows)
        assert all(plaintext_key not in str(row.metadata_json) for row in audit_rows)
    finally:
        async with session_factory.begin() as session:
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.execute(delete(ArtifactBlob).where(ArtifactBlob.sha256 == dataset_sha))
        await engine.dispose()


@pytest.mark.integration
async def test_multi_dispatcher_recovers_lost_ack_without_duplicate_audit() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    tenant_id = uuid4()
    outbox_id = uuid4()
    api_key_id = uuid4()
    trace_id = uuid4().hex
    try:
        async with session_factory.begin() as session:
            session.add(Tenant(id=tenant_id, slug=f"audit-{tenant_id.hex}", name="Audit test"))
            await session.flush()
            session.add(
                McpAuditOutbox(
                    id=outbox_id,
                    tenant_id=tenant_id,
                    api_key_id=api_key_id,
                    actor_id=str(api_key_id),
                    tool_name="submit_evaluation",
                    call_identity="idempotency:lost-ack",
                    trace_id=trace_id,
                    outcome_status="succeeded",
                )
            )
            session.add(
                AuditEvent(
                    id=outbox_id,
                    tenant_id=tenant_id,
                    actor_id=str(api_key_id),
                    action="mcp.tool_called",
                    resource_type="mcp_tool",
                    resource_id=UUID(hex=trace_id),
                    metadata_json={"source_outbox_id": str(outbox_id)},
                )
            )

        def build_dispatcher(dispatcher_id: str) -> AuditDispatcher:
            return AuditDispatcher(
                store=SQLAlchemyAuditOutboxStore(
                    session_factory,
                    dispatcher_id=dispatcher_id,
                    lease_seconds=30,
                ),
                sink=SQLAlchemyAuditEventSink(session_factory),
                delivery_timeout_seconds=5,
                retry_base_seconds=1,
                retry_max_seconds=60,
            )

        results = await asyncio.gather(
            build_dispatcher("system-a").dispatch_once(limit=1),
            build_dispatcher("system-b").dispatch_once(limit=1),
        )

        assert sum(result.claimed for result in results) == 1
        assert sum(result.delivered for result in results) == 1
        async with session_factory() as session:
            audit_events = (
                (await session.execute(select(AuditEvent).where(AuditEvent.id == outbox_id)))
                .scalars()
                .all()
            )
            outbox = await session.get(McpAuditOutbox, outbox_id)
        assert len(audit_events) == 1
        assert outbox is not None
        assert outbox.delivery_status == "DELIVERED"
        assert outbox.attempt_count == 1
        assert outbox.lease_version == 1
    finally:
        async with session_factory.begin() as session:
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await engine.dispose()
