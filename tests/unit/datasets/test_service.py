from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio.session import async_sessionmaker
from sqlalchemy.sql import Executable

from app.auth.principals import Principal
from app.datasets.service import (
    DatasetNotFoundError,
    SQLAlchemyDatasetService,
    build_get_dataset_statement,
    build_get_dataset_version_statement,
    build_lock_dataset_statement,
)
from app.datasets.validation import DatasetValidationError

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
DATASET_ID = UUID("00000000-0000-0000-0000-000000000301")
VERSION_ID = UUID("00000000-0000-0000-0000-000000000401")


def compiled_sql(statement: Executable) -> str:
    compiled = statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    return " ".join(str(compiled).lower().split())


def test_get_dataset_statement_filters_resource_and_server_tenant() -> None:
    sql = compiled_sql(build_get_dataset_statement(TENANT_ID, DATASET_ID))

    assert f"datasets.id = '{DATASET_ID}'" in sql
    assert f"datasets.tenant_id = '{TENANT_ID}'" in sql


def test_get_version_statement_filters_full_resource_chain_and_tenant() -> None:
    sql = compiled_sql(
        build_get_dataset_version_statement(
            TENANT_ID,
            DATASET_ID,
            VERSION_ID,
        )
    )

    assert "join datasets on datasets.id = dataset_versions.dataset_id" in sql
    assert f"dataset_versions.id = '{VERSION_ID}'" in sql
    assert f"dataset_versions.dataset_id = '{DATASET_ID}'" in sql
    assert f"dataset_versions.tenant_id = '{TENANT_ID}'" in sql
    assert f"datasets.tenant_id = '{TENANT_ID}'" in sql


def test_upload_lock_statement_filters_tenant_before_row_lock() -> None:
    sql = compiled_sql(build_lock_dataset_statement(TENANT_ID, DATASET_ID))

    assert f"datasets.id = '{DATASET_ID}'" in sql
    assert f"datasets.tenant_id = '{TENANT_ID}'" in sql
    assert sql.endswith("for update")


class ArtifactStoreThatMustNotBeCalled:
    async def put_bytes(self, _content: bytes) -> None:
        raise AssertionError("invalid JSONL must not reach artifact storage")


async def test_invalid_version_fails_before_artifact_or_database_work() -> None:
    service = SQLAlchemyDatasetService(
        session_factory=cast(async_sessionmaker[AsyncSession], object()),
        artifact_store=ArtifactStoreThatMustNotBeCalled(),
    )

    with pytest.raises(DatasetValidationError) as captured:
        await service.create_dataset_version(
            principal=cast(object, None),
            dataset_id=DATASET_ID,
            content=b'{"case_id":',
            media_type="application/jsonl",
        )

    assert captured.value.code == "invalid_json"


class MissingDatasetResult:
    @staticmethod
    def scalar_one_or_none() -> None:
        return None


class MissingDatasetSession:
    async def __aenter__(self) -> "MissingDatasetSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> MissingDatasetResult:
        return MissingDatasetResult()


class MissingDatasetSessionFactory:
    def __call__(self) -> MissingDatasetSession:
        return MissingDatasetSession()


async def test_missing_or_cross_tenant_dataset_fails_before_artifact_write() -> None:
    service = SQLAlchemyDatasetService(
        session_factory=cast(
            async_sessionmaker[AsyncSession],
            MissingDatasetSessionFactory(),
        ),
        artifact_store=ArtifactStoreThatMustNotBeCalled(),
    )
    principal = Principal(
        tenant_id=TENANT_ID,
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        key_prefix="evk_001122334455",
    )
    content = b'{"case_id":"case-1","question":"q","expected_answer":"a","metadata":{}}\n'

    with pytest.raises(DatasetNotFoundError):
        await service.create_dataset_version(
            principal=principal,
            dataset_id=DATASET_ID,
            content=content,
            media_type="application/jsonl",
        )
