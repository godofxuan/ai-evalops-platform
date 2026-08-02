from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.artifacts.repository import (
    ArtifactMetadataIntegrityError,
    build_get_artifact_reference_statement,
    ensure_artifact_reference,
)
from app.artifacts.storage import StoredArtifact
from app.domain.enums import ArtifactType

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
REFERENCE_ID = UUID("00000000-0000-0000-0000-000000000701")


def compile_postgresql(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_reference_lookup_authorizes_tenant_and_run_before_joining_blob() -> None:
    sql = compile_postgresql(
        build_get_artifact_reference_statement(
            tenant_id=TENANT_ID,
            reference_id=REFERENCE_ID,
            run_id=RUN_ID,
        )
    )

    assert "artifact_references.tenant_id" in sql
    assert "artifact_references.run_id" in sql
    assert "artifact_references.id" in sql
    assert "JOIN artifact_blobs" in sql


def test_reference_lookup_without_run_only_allows_dataset_reference() -> None:
    sql = compile_postgresql(
        build_get_artifact_reference_statement(
            tenant_id=TENANT_ID,
            reference_id=REFERENCE_ID,
        )
    )

    assert "artifact_references.run_id IS NULL" in sql


@pytest.mark.parametrize(
    ("artifact_type", "run_id"),
    [
        (ArtifactType.DATASET_SOURCE, RUN_ID),
        (ArtifactType.SUMMARY_REPORT, None),
    ],
)
async def test_registration_rejects_inconsistent_run_owner_scope_before_database_io(
    artifact_type: ArtifactType,
    run_id: UUID | None,
) -> None:
    stored = StoredArtifact(
        sha256="a" * 64,
        size_bytes=1,
        relative_path=Path("aa", "a" * 64),
        created=True,
    )

    with pytest.raises(ArtifactMetadataIntegrityError):
        await ensure_artifact_reference(
            cast(AsyncSession, object()),
            tenant_id=TENANT_ID,
            run_id=run_id,
            artifact_type=artifact_type,
            media_type="application/json",
            stored=stored,
        )
