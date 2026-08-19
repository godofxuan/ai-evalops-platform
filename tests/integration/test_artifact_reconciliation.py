import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete

from app.artifacts.reconciliation import ArtifactReconciler
from app.artifacts.storage import LocalArtifactStore, StoredArtifact, StoredObjectInfo
from app.core.config import Settings
from app.domain.enums import ArtifactType
from app.persistence.database import create_database_engine, create_session_factory
from app.persistence.orm_models import (
    ArtifactBlob,
    ArtifactReconciliationEvent,
    ArtifactReference,
    Tenant,
)


class FailOnceStore:
    def __init__(self, inner: LocalArtifactStore, fail_sha256: str) -> None:
        self.inner = inner
        self.fail_sha256 = fail_sha256
        self.failed = False

    async def put_bytes(self, content: bytes) -> StoredArtifact:
        return await self.inner.put_bytes(content)

    async def get_bytes(self, sha256: str) -> bytes:
        return await self.inner.get_bytes(sha256)

    async def check_ready(self) -> None:
        await self.inner.check_ready()

    async def list_objects(self) -> list[StoredObjectInfo]:
        return await self.inner.list_objects()

    async def delete_bytes(self, sha256: str) -> bool:
        if sha256 == self.fail_sha256 and not self.failed:
            self.failed = True
            raise OSError("injected retryable delete failure")
        return await self.inner.delete_bytes(sha256)


@pytest.mark.integration
async def test_orphan_reconciliation_is_dry_run_safe_rechecks_and_retries(
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
    store = LocalArtifactStore(tmp_path)
    orphan = await store.put_bytes(b"put succeeded, database rolled back")
    grace = await store.put_bytes(b"inside grace period")
    race = await store.put_bytes(b"referenced between scan and delete")
    shared = await store.put_bytes(b"same digest referenced by two tenants")
    retry = await store.put_bytes(b"delete fails once")
    old_time = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    for item in (orphan, race, shared, retry):
        await asyncio.to_thread(os.utime, tmp_path / item.relative_path, (old_time, old_time))
    tenant_a, tenant_b = uuid4(), uuid4()
    shared_refs = (uuid4(), uuid4())
    race_ref = uuid4()
    all_shas = {orphan.sha256, grace.sha256, race.sha256, shared.sha256, retry.sha256}
    try:
        async with session_factory.begin() as session:
            session.add_all(
                [
                    Tenant(id=tenant_a, slug=f"gc-a-{tenant_a.hex}", name="GC A"),
                    Tenant(id=tenant_b, slug=f"gc-b-{tenant_b.hex}", name="GC B"),
                    ArtifactBlob(
                        sha256=shared.sha256,
                        byte_size=shared.size_bytes,
                        storage_path=shared.relative_path.as_posix(),
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    ArtifactReference(
                        id=shared_refs[0],
                        tenant_id=tenant_a,
                        artifact_type=ArtifactType.DATASET_SOURCE,
                        blob_sha256=shared.sha256,
                        media_type="application/octet-stream",
                    ),
                    ArtifactReference(
                        id=shared_refs[1],
                        tenant_id=tenant_b,
                        artifact_type=ArtifactType.DATASET_SOURCE,
                        blob_sha256=shared.sha256,
                        media_type="application/octet-stream",
                    ),
                ]
            )

        def clock() -> datetime:
            return datetime(2026, 8, 20, tzinfo=UTC)

        dry_report = await ArtifactReconciler(session_factory, store, now=clock).reconcile(
            grace_period=timedelta(days=1)
        )
        assert dry_report.dry_run is True
        assert await store.get_bytes(orphan.sha256) == b"put succeeded, database rolled back"
        assert grace.sha256 not in {item.sha256 for item in dry_report.items}

        async def establish_racing_reference(sha256: str) -> None:
            if sha256 != race.sha256:
                return
            async with session_factory.begin() as session:
                session.add(
                    ArtifactBlob(
                        sha256=race.sha256,
                        byte_size=race.size_bytes,
                        storage_path=race.relative_path.as_posix(),
                    )
                )
                await session.flush()
                session.add(
                    ArtifactReference(
                        id=race_ref,
                        tenant_id=tenant_a,
                        artifact_type=ArtifactType.DATASET_SOURCE,
                        blob_sha256=race.sha256,
                        media_type="application/octet-stream",
                    )
                )

        failing_store = FailOnceStore(store, retry.sha256)
        active_report = await ArtifactReconciler(
            session_factory,
            failing_store,
            now=clock,
            candidate_observer=establish_racing_reference,
        ).reconcile(grace_period=timedelta(days=1), dry_run=False)
        statuses = {item.sha256: item.status for item in active_report.items}
        assert statuses[orphan.sha256] == "deleted"
        assert statuses[race.sha256] == "recheck_blocked"
        assert statuses[shared.sha256] == "referenced"
        assert statuses[retry.sha256] == "delete_failed"
        assert await store.get_bytes(race.sha256) == b"referenced between scan and delete"
        assert await store.get_bytes(shared.sha256) == b"same digest referenced by two tenants"

        retry_report = await ArtifactReconciler(
            session_factory, failing_store, now=clock
        ).reconcile(grace_period=timedelta(days=1), dry_run=False)
        assert {item.sha256: item.status for item in retry_report.items}[retry.sha256] == "deleted"
        final_report = await ArtifactReconciler(session_factory, store, now=clock).reconcile(
            grace_period=timedelta(days=1), dry_run=False
        )
        assert orphan.sha256 not in {item.sha256 for item in final_report.items}
        assert retry.sha256 not in {item.sha256 for item in final_report.items}
    finally:
        async with session_factory.begin() as session:
            await session.execute(
                delete(ArtifactReconciliationEvent).where(
                    ArtifactReconciliationEvent.blob_sha256.in_(all_shas)
                )
            )
            await session.execute(delete(Tenant).where(Tenant.id.in_((tenant_a, tenant_b))))
            await session.execute(delete(ArtifactBlob).where(ArtifactBlob.sha256.in_(all_shas)))
        for sha256 in all_shas:
            await store.delete_bytes(sha256)
        await engine.dispose()
