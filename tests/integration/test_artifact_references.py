import asyncio
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.artifacts.repository import (
    SQLAlchemyArtifactReferenceGateway,
    ensure_artifact_reference,
)
from app.artifacts.service import ArtifactAccessService, ArtifactReferenceNotFoundError
from app.artifacts.storage import ArtifactIntegrityError, LocalArtifactStore, StoredArtifact
from app.core.config import Settings
from app.domain.enums import ArtifactType
from app.persistence.database import (
    AsyncSessionFactory,
    create_database_engine,
    create_session_factory,
)
from app.persistence.orm_models import (
    APIKey,
    ArtifactBlob,
    ArtifactReference,
    Dataset,
    DatasetVersion,
    EvaluationRun,
    Tenant,
)


@dataclass(frozen=True, slots=True)
class SeededOwner:
    tenant_id: UUID
    api_key_id: UUID
    dataset_id: UUID
    dataset_version_id: UUID
    dataset_reference_id: UUID
    dataset_blob_sha256: str
    run_ids: tuple[UUID, ...]


class ExpectedReferenceRollback(RuntimeError):
    pass


async def _seed_owner(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    run_ids: tuple[UUID, ...],
) -> SeededOwner:
    api_key_id = uuid4()
    dataset_id = uuid4()
    dataset_version_id = uuid4()
    dataset_reference_id = uuid4()
    dataset_blob_sha256 = hashlib.sha256(f"dataset:{tenant_id}".encode()).hexdigest()

    session.add(
        Tenant(
            id=tenant_id,
            slug=f"artifact-{tenant_id.hex}",
            name="Artifact reference integration tenant",
        )
    )
    await session.flush()
    session.add_all(
        [
            APIKey(
                id=api_key_id,
                tenant_id=tenant_id,
                name="artifact-reference-owner",
                key_prefix=f"ar_{tenant_id.hex[:12]}",
                key_hash="not-a-real-key",
            ),
            Dataset(
                id=dataset_id,
                tenant_id=tenant_id,
                name=f"artifact-dataset-{tenant_id.hex}",
            ),
            ArtifactBlob(
                sha256=dataset_blob_sha256,
                byte_size=1,
                storage_path=f"{dataset_blob_sha256[:2]}/{dataset_blob_sha256}",
            ),
        ]
    )
    await session.flush()
    session.add(
        ArtifactReference(
            id=dataset_reference_id,
            blob_sha256=dataset_blob_sha256,
            tenant_id=tenant_id,
            artifact_type=ArtifactType.DATASET_SOURCE,
            media_type="application/x-ndjson",
        )
    )
    await session.flush()
    session.add(
        DatasetVersion(
            id=dataset_version_id,
            dataset_id=dataset_id,
            tenant_id=tenant_id,
            artifact_id=dataset_reference_id,
            version=1,
            schema_version="1",
            sha256=dataset_blob_sha256,
            case_count=1,
        )
    )
    await session.flush()
    session.add_all(
        [
            EvaluationRun(
                id=run_id,
                tenant_id=tenant_id,
                dataset_version_id=dataset_version_id,
                dataset_hash=dataset_blob_sha256,
                idempotency_key=f"artifact-reference-{run_id}",
                request_hash=hashlib.sha256(f"request:{run_id}".encode()).hexdigest(),
                target_type="mock",
                target_config_json={},
                target_config_hash="b" * 64,
                evaluator_type="basic_answer",
                evaluator_config_json={},
                evaluator_config_hash="c" * 64,
                target_version="mock-v1",
                evaluator_version="basic-answer-v1",
                total_jobs=0,
                created_by=api_key_id,
            )
            for run_id in run_ids
        ]
    )
    await session.flush()
    return SeededOwner(
        tenant_id=tenant_id,
        api_key_id=api_key_id,
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
        dataset_reference_id=dataset_reference_id,
        dataset_blob_sha256=dataset_blob_sha256,
        run_ids=run_ids,
    )


async def _register_run_reference(
    session_factory: AsyncSessionFactory,
    *,
    tenant_id: UUID,
    run_id: UUID,
    stored: StoredArtifact,
) -> UUID:
    async with session_factory.begin() as session:
        reference = await ensure_artifact_reference(
            session,
            tenant_id=tenant_id,
            run_id=run_id,
            artifact_type=ArtifactType.SUMMARY_REPORT,
            media_type="application/json",
            stored=stored,
        )
        return reference.id


@pytest.mark.integration
async def test_real_artifact_references_separate_dedup_ownership_and_cleanup(
    tmp_path: Path,
) -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with migrated real PostgreSQL")
    database_url = os.getenv("EVALOPS_DATABASE_URL")
    if database_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL")

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(database_url),
        redis_url=SecretStr(os.getenv("EVALOPS_REDIS_URL", "redis://localhost:6379/0")),
        artifact_root=tmp_path,
    )
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    store = LocalArtifactStore(tmp_path)
    gateway = SQLAlchemyArtifactReferenceGateway(session_factory)
    access = ArtifactAccessService(gateway=gateway, store=store)
    tenant_a_id = uuid4()
    tenant_b_id = uuid4()
    run_a1_id = uuid4()
    run_a2_id = uuid4()
    run_b1_id = uuid4()
    owners: tuple[SeededOwner, ...] = ()

    try:
        async with session_factory.begin() as session:
            owner_a = await _seed_owner(
                session,
                tenant_id=tenant_a_id,
                run_ids=(run_a1_id, run_a2_id),
            )
            owner_b = await _seed_owner(
                session,
                tenant_id=tenant_b_id,
                run_ids=(run_b1_id,),
            )
            owners = (owner_a, owner_b)

        content = b'{"schema_version":"1","shared":true}\n'
        stored = await store.put_bytes(content)
        reference_a1, reference_a2, reference_b1, reference_a1_retry = await asyncio.gather(
            _register_run_reference(
                session_factory,
                tenant_id=tenant_a_id,
                run_id=run_a1_id,
                stored=stored,
            ),
            _register_run_reference(
                session_factory,
                tenant_id=tenant_a_id,
                run_id=run_a2_id,
                stored=stored,
            ),
            _register_run_reference(
                session_factory,
                tenant_id=tenant_b_id,
                run_id=run_b1_id,
                stored=stored,
            ),
            _register_run_reference(
                session_factory,
                tenant_id=tenant_a_id,
                run_id=run_a1_id,
                stored=stored,
            ),
        )

        assert reference_a1 == reference_a1_retry
        assert len({reference_a1, reference_a2, reference_b1}) == 3
        async with session_factory() as session:
            blob_count = await session.scalar(
                select(ArtifactBlob).where(ArtifactBlob.sha256 == stored.sha256)
            )
            references = (
                (
                    await session.execute(
                        select(ArtifactReference).where(
                            ArtifactReference.blob_sha256 == stored.sha256
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert blob_count is not None
        assert len(references) == 3

        assert (
            await access.read_bytes(
                tenant_id=tenant_a_id,
                reference_id=reference_a1,
                run_id=run_a1_id,
            )
            == content
        )
        with pytest.raises(ArtifactReferenceNotFoundError):
            await access.read_bytes(
                tenant_id=tenant_b_id,
                reference_id=reference_a1,
                run_id=run_a1_id,
            )
        with pytest.raises(ArtifactReferenceNotFoundError):
            await access.read_bytes(
                tenant_id=tenant_a_id,
                reference_id=reference_a1,
                run_id=run_a2_id,
            )
        with pytest.raises(ArtifactReferenceNotFoundError):
            await access.read_bytes(
                tenant_id=tenant_a_id,
                reference_id=reference_a1,
            )

        await access.delete_reference(
            tenant_id=tenant_a_id,
            reference_id=reference_a1,
            run_id=run_a1_id,
        )
        assert (tmp_path / stored.relative_path).is_file()
        assert (
            await access.read_bytes(
                tenant_id=tenant_a_id,
                reference_id=reference_a2,
                run_id=run_a2_id,
            )
            == content
        )
        await access.delete_reference(
            tenant_id=tenant_a_id,
            reference_id=reference_a2,
            run_id=run_a2_id,
        )
        assert (tmp_path / stored.relative_path).is_file()
        await access.delete_reference(
            tenant_id=tenant_b_id,
            reference_id=reference_b1,
            run_id=run_b1_id,
        )
        assert not (tmp_path / stored.relative_path).exists()

        missing_stored = await store.put_bytes(b"database reference, missing file")
        missing_reference = await _register_run_reference(
            session_factory,
            tenant_id=tenant_a_id,
            run_id=run_a1_id,
            stored=missing_stored,
        )
        assert await store.delete_bytes(missing_stored.sha256) is True
        with pytest.raises(ArtifactIntegrityError):
            await access.read_bytes(
                tenant_id=tenant_a_id,
                reference_id=missing_reference,
                run_id=run_a1_id,
            )
        await access.delete_reference(
            tenant_id=tenant_a_id,
            reference_id=missing_reference,
            run_id=run_a1_id,
        )

        orphan_stored = await store.put_bytes(b"file created before database rollback")
        rolled_back_reference_id: UUID | None = None
        with pytest.raises(ExpectedReferenceRollback):
            async with session_factory.begin() as session:
                rolled_back = await ensure_artifact_reference(
                    session,
                    tenant_id=tenant_a_id,
                    run_id=run_a1_id,
                    artifact_type=ArtifactType.FAILURE_CASES,
                    media_type="application/json",
                    stored=orphan_stored,
                )
                rolled_back_reference_id = rolled_back.id
                raise ExpectedReferenceRollback
        assert rolled_back_reference_id is not None
        assert (
            await gateway.get_location(
                tenant_id=tenant_a_id,
                reference_id=rolled_back_reference_id,
                run_id=run_a1_id,
            )
            is None
        )
        assert (tmp_path / orphan_stored.relative_path).is_file()
        assert await access.collect_orphan_blob(sha256=orphan_stored.sha256) is True
        assert not (tmp_path / orphan_stored.relative_path).exists()
    finally:
        if owners:
            async with session_factory.begin() as session:
                tenant_ids = tuple(owner.tenant_id for owner in owners)
                run_ids = tuple(run_id for owner in owners for run_id in owner.run_ids)
                blob_sha256s = set(
                    (
                        await session.execute(
                            select(ArtifactReference.blob_sha256).where(
                                ArtifactReference.tenant_id.in_(tenant_ids)
                            )
                        )
                    ).scalars()
                )
                blob_sha256s.update(owner.dataset_blob_sha256 for owner in owners)
                await session.execute(delete(EvaluationRun).where(EvaluationRun.id.in_(run_ids)))
                await session.execute(
                    delete(DatasetVersion).where(
                        DatasetVersion.id.in_(tuple(owner.dataset_version_id for owner in owners))
                    )
                )
                await session.execute(
                    delete(Dataset).where(
                        Dataset.id.in_(tuple(owner.dataset_id for owner in owners))
                    )
                )
                await session.execute(
                    delete(ArtifactReference).where(ArtifactReference.tenant_id.in_(tenant_ids))
                )
                await session.flush()
                if blob_sha256s:
                    await session.execute(
                        delete(ArtifactBlob).where(
                            ArtifactBlob.sha256.in_(blob_sha256s),
                            ~exists(
                                select(ArtifactReference.id).where(
                                    ArtifactReference.blob_sha256 == ArtifactBlob.sha256
                                )
                            ),
                        )
                    )
                await session.execute(
                    delete(APIKey).where(APIKey.id.in_(tuple(owner.api_key_id for owner in owners)))
                )
                await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
        await engine.dispose()
