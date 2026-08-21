from uuid import UUID

import pytest

from app.artifacts.service import (
    ArtifactAccessService,
    ArtifactReferenceLocation,
    ArtifactReferenceNotFoundError,
    DeletedArtifactReference,
)
from app.artifacts.storage import StoredArtifact

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
REFERENCE_ID = UUID("00000000-0000-0000-0000-000000000701")
DELETION_TOKEN = UUID("00000000-0000-0000-0000-000000000801")
SHA256 = "a" * 64


class StaticArtifactGateway:
    def __init__(self, location: ArtifactReferenceLocation | None) -> None:
        self.location = location

    async def get_location(
        self,
        *,
        tenant_id: UUID,
        reference_id: UUID,
        run_id: UUID | None,
    ) -> ArtifactReferenceLocation | None:
        del tenant_id, reference_id, run_id
        return self.location

    async def delete_reference(
        self,
        *,
        tenant_id: UUID,
        reference_id: UUID,
        run_id: UUID | None,
    ) -> DeletedArtifactReference | None:
        del tenant_id, reference_id, run_id
        raise AssertionError("delete should not be called")

    async def claim_unreferenced_blob(self, *, sha256: str) -> bool:
        del sha256
        raise AssertionError("orphan cleanup should not be called")

    async def finalize_blob_deletion(self, **kwargs: object) -> None:
        del kwargs
        raise AssertionError("finalize should not be called")


class StaticDeletableStore:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.requested_sha256: str | None = None
        self.deleted_sha256: str | None = None

    async def put_bytes(self, content: bytes) -> StoredArtifact:
        del content
        raise AssertionError("put should not be called")

    async def get_bytes(self, sha256: str) -> bytes:
        self.requested_sha256 = sha256
        return self.content

    async def delete_bytes(self, sha256: str) -> bool:
        self.deleted_sha256 = sha256
        return True


class StaticDeletingGateway:
    def __init__(self, deleted: DeletedArtifactReference | None) -> None:
        self.deleted = deleted
        self.finalized: list[dict[str, object]] = []

    async def get_location(
        self,
        *,
        tenant_id: UUID,
        reference_id: UUID,
        run_id: UUID | None,
    ) -> ArtifactReferenceLocation | None:
        del tenant_id, reference_id, run_id
        raise AssertionError("read should not be called")

    async def delete_reference(
        self,
        *,
        tenant_id: UUID,
        reference_id: UUID,
        run_id: UUID | None,
    ) -> DeletedArtifactReference | None:
        del tenant_id, reference_id, run_id
        return self.deleted

    async def claim_unreferenced_blob(self, *, sha256: str) -> bool:
        del sha256
        raise AssertionError("orphan cleanup should not be called")

    async def finalize_blob_deletion(
        self,
        *,
        sha256: str,
        deletion_token: UUID,
        succeeded: bool,
        error_code: str | None = None,
    ) -> None:
        self.finalized.append(
            {
                "sha256": sha256,
                "deletion_token": deletion_token,
                "succeeded": succeeded,
                "error_code": error_code,
            }
        )


class StaticOrphanGateway(StaticDeletingGateway):
    def __init__(self, *, safe_to_delete: bool) -> None:
        super().__init__(None)
        self.safe_to_delete = safe_to_delete

    async def claim_unreferenced_blob(self, *, sha256: str) -> bool:
        del sha256
        return self.safe_to_delete


async def test_read_bytes_resolves_authorized_reference_before_blob() -> None:
    gateway = StaticArtifactGateway(
        ArtifactReferenceLocation(reference_id=REFERENCE_ID, blob_sha256=SHA256)
    )
    store = StaticDeletableStore(b"tenant-owned artifact")
    service = ArtifactAccessService(gateway=gateway, store=store)

    content = await service.read_bytes(
        tenant_id=TENANT_ID,
        reference_id=REFERENCE_ID,
        run_id=RUN_ID,
    )

    assert content == b"tenant-owned artifact"
    assert store.requested_sha256 == SHA256


async def test_read_bytes_hides_cross_tenant_reference_without_touching_blob() -> None:
    store = StaticDeletableStore(b"must not be disclosed")
    service = ArtifactAccessService(
        gateway=StaticArtifactGateway(None),
        store=store,
    )

    with pytest.raises(ArtifactReferenceNotFoundError):
        await service.read_bytes(
            tenant_id=TENANT_ID,
            reference_id=REFERENCE_ID,
            run_id=RUN_ID,
        )

    assert store.requested_sha256 is None


async def test_delete_reference_keeps_blob_while_another_reference_exists() -> None:
    store = StaticDeletableStore(b"shared content")
    service = ArtifactAccessService(
        gateway=StaticDeletingGateway(
            DeletedArtifactReference(blob_sha256=SHA256, last_reference=False)
        ),
        store=store,
    )

    await service.delete_reference(
        tenant_id=TENANT_ID,
        reference_id=REFERENCE_ID,
        run_id=RUN_ID,
    )

    assert store.deleted_sha256 is None


async def test_delete_last_reference_removes_physical_blob() -> None:
    store = StaticDeletableStore(b"last content")
    service = ArtifactAccessService(
        gateway=StaticDeletingGateway(
            DeletedArtifactReference(
                blob_sha256=SHA256,
                last_reference=True,
                deletion_token=DELETION_TOKEN,
            )
        ),
        store=store,
    )

    await service.delete_reference(
        tenant_id=TENANT_ID,
        reference_id=REFERENCE_ID,
        run_id=RUN_ID,
    )

    assert store.deleted_sha256 == SHA256


async def test_collect_orphan_blob_deletes_file_only_after_database_claim() -> None:
    store = StaticDeletableStore(b"unreferenced content")
    service = ArtifactAccessService(
        gateway=StaticOrphanGateway(safe_to_delete=True),
        store=store,
    )

    collected = await service.collect_orphan_blob(sha256=SHA256)

    assert collected is True
    assert store.deleted_sha256 == SHA256
