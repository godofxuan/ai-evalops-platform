import asyncio
import hashlib
import os
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, exists, select

from app.auth.api_keys import generate_api_key
from app.core.config import Settings
from app.domain.enums import APIKeyStatus
from app.main import create_app
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    APIKey,
    ArtifactBlob,
    ArtifactReference,
    Dataset,
    DatasetVersion,
    Tenant,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def list_artifact_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()]


@pytest.mark.integration
async def test_real_identity_tenant_dataset_version_and_artifact_boundaries(
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
        alembic_config_path=PROJECT_ROOT / "alembic.ini",
    )
    tenant_a_id = uuid4()
    tenant_b_id = uuid4()
    tenant_ids = (tenant_a_id, tenant_b_id)
    generated_a = generate_api_key()
    generated_b = generate_api_key()
    raw_key_a = generated_a.plaintext.get_secret_value()
    raw_key_b = generated_b.plaintext.get_secret_value()
    application = create_app(settings=settings)

    async with application.router.lifespan_context(application):
        session_factory = cast(AsyncSessionFactory, application.state.session_factory)
        async with session_factory.begin() as session:
            session.add_all(
                [
                    Tenant(
                        id=tenant_a_id,
                        slug=f"integration-a-{uuid4().hex}",
                        name="Integration tenant A",
                    ),
                    Tenant(
                        id=tenant_b_id,
                        slug=f"integration-b-{uuid4().hex}",
                        name="Integration tenant B",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    APIKey(
                        tenant_id=tenant_a_id,
                        name="integration-a",
                        key_prefix=generated_a.prefix,
                        key_hash=generated_a.key_hash,
                    ),
                    APIKey(
                        tenant_id=tenant_b_id,
                        name="integration-b",
                        key_prefix=generated_b.prefix,
                        key_hash=generated_b.key_hash,
                    ),
                ]
            )

        transport = ASGITransport(app=application)
        content = b'{"case_id":"case-1","question":"q","expected_answer":"a","metadata":{}}\n'
        content_sha256 = hashlib.sha256(content).hexdigest()
        dataset_ids: list[UUID] = []
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_a = await client.post(
                    "/api/v1/datasets",
                    headers={"Authorization": f"Bearer {raw_key_a}"},
                    json={"name": "integration-a"},
                )
                assert create_a.status_code == 201
                dataset_a_id = UUID(create_a.json()["id"])
                dataset_ids.append(dataset_a_id)

                upload_a = await client.post(
                    f"/api/v1/datasets/{dataset_a_id}/versions",
                    headers={"Authorization": f"Bearer {raw_key_a}"},
                    files={"file": ("cases.jsonl", content, "application/x-ndjson")},
                )
                assert upload_a.status_code == 201
                assert upload_a.json()["version"] == 1
                version_a_id = UUID(upload_a.json()["id"])

                duplicate_a = await client.post(
                    f"/api/v1/datasets/{dataset_a_id}/versions",
                    headers={"Authorization": f"Bearer {raw_key_a}"},
                    files={"file": ("same.jsonl", content, "application/jsonl")},
                )
                assert duplicate_a.status_code == 409
                assert duplicate_a.json()["error"]["code"] == "dataset_version_exists"

                cross_tenant_dataset = await client.get(
                    f"/api/v1/datasets/{dataset_a_id}",
                    headers={"Authorization": f"Bearer {raw_key_b}"},
                )
                cross_tenant_version = await client.get(
                    f"/api/v1/datasets/{dataset_a_id}/versions/{version_a_id}",
                    headers={"Authorization": f"Bearer {raw_key_b}"},
                )
                assert cross_tenant_dataset.status_code == 404
                assert cross_tenant_version.status_code == 404
                assert cross_tenant_dataset.json() == cross_tenant_version.json()

                files_before_cross_upload = await asyncio.to_thread(
                    list_artifact_files,
                    tmp_path,
                )
                cross_tenant_upload = await client.post(
                    f"/api/v1/datasets/{dataset_a_id}/versions",
                    headers={"Authorization": f"Bearer {raw_key_b}"},
                    files={
                        "file": (
                            "unauthorized.jsonl",
                            content.replace(b"case-1", b"case-cross-tenant"),
                            "application/jsonl",
                        )
                    },
                )
                assert cross_tenant_upload.status_code == 404
                assert (
                    await asyncio.to_thread(list_artifact_files, tmp_path)
                    == files_before_cross_upload
                )

                create_b = await client.post(
                    "/api/v1/datasets",
                    headers={"Authorization": f"Bearer {raw_key_b}"},
                    json={"name": "integration-b"},
                )
                assert create_b.status_code == 201
                dataset_b_id = UUID(create_b.json()["id"])
                dataset_ids.append(dataset_b_id)

                upload_b = await client.post(
                    f"/api/v1/datasets/{dataset_b_id}/versions",
                    headers={"Authorization": f"Bearer {raw_key_b}"},
                    files={"file": ("same.jsonl", content, "application/jsonl")},
                )
                assert upload_b.status_code == 201

                async with session_factory.begin() as session:
                    key_b = (
                        await session.execute(
                            select(APIKey).where(APIKey.key_prefix == generated_b.prefix)
                        )
                    ).scalar_one()
                    key_b.status = APIKeyStatus.REVOKED

                revoked = await client.get(
                    f"/api/v1/datasets/{dataset_b_id}",
                    headers={"Authorization": f"Bearer {raw_key_b}"},
                )
                assert revoked.status_code == 401
                assert revoked.json()["error"]["code"] == "invalid_api_key"

            async with session_factory() as session:
                references = (
                    (
                        await session.execute(
                            select(ArtifactReference).where(
                                ArtifactReference.tenant_id.in_(tenant_ids)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                blobs = (
                    (
                        await session.execute(
                            select(ArtifactBlob).where(ArtifactBlob.sha256 == content_sha256)
                        )
                    )
                    .scalars()
                    .all()
                )
                persisted_keys = (
                    (await session.execute(select(APIKey).where(APIKey.tenant_id.in_(tenant_ids))))
                    .scalars()
                    .all()
                )

            assert len(references) == 2
            assert {reference.tenant_id for reference in references} == set(tenant_ids)
            assert {reference.blob_sha256 for reference in references} == {content_sha256}
            assert len(blobs) == 1
            assert len(await asyncio.to_thread(list_artifact_files, tmp_path)) == 1
            assert all(raw_key_a not in key.key_hash for key in persisted_keys)
            assert all(raw_key_b not in key.key_hash for key in persisted_keys)
            assert all(key.last_used_at is not None for key in persisted_keys)
        finally:
            async with session_factory.begin() as session:
                if dataset_ids:
                    await session.execute(
                        delete(DatasetVersion).where(DatasetVersion.dataset_id.in_(dataset_ids))
                    )
                    await session.execute(delete(Dataset).where(Dataset.id.in_(dataset_ids)))
                await session.execute(
                    delete(ArtifactReference).where(ArtifactReference.tenant_id.in_(tenant_ids))
                )
                await session.execute(
                    delete(ArtifactBlob).where(
                        ArtifactBlob.sha256 == content_sha256,
                        ~exists(
                            select(ArtifactReference.id).where(
                                ArtifactReference.blob_sha256 == ArtifactBlob.sha256
                            )
                        ),
                    )
                )
                await session.execute(delete(APIKey).where(APIKey.tenant_id.in_(tenant_ids)))
                await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
