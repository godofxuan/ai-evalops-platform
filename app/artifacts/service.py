from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.artifacts.storage import DeletableArtifactStore


@dataclass(frozen=True, slots=True)
class ArtifactReferenceLocation:
    reference_id: UUID
    blob_sha256: str


@dataclass(frozen=True, slots=True)
class DeletedArtifactReference:
    blob_sha256: str
    last_reference: bool


class ArtifactReferenceNotFoundError(Exception):
    """Hide absent and cross-tenant references behind one outcome."""


class ArtifactReferenceGateway(Protocol):
    async def get_location(
        self,
        *,
        tenant_id: UUID,
        reference_id: UUID,
        run_id: UUID | None,
    ) -> ArtifactReferenceLocation | None:
        """Resolve a reference only inside its tenant and optional Run owner."""

    async def delete_reference(
        self,
        *,
        tenant_id: UUID,
        reference_id: UUID,
        run_id: UUID | None,
    ) -> DeletedArtifactReference | None:
        """Delete an authorized reference and report whether it was the last."""

    async def claim_unreferenced_blob(self, *, sha256: str) -> bool:
        """Remove unreferenced metadata before physical orphan cleanup."""


class ArtifactAccessService:
    def __init__(
        self,
        *,
        gateway: ArtifactReferenceGateway,
        store: DeletableArtifactStore,
    ) -> None:
        self._gateway = gateway
        self._store = store

    async def read_bytes(
        self,
        *,
        tenant_id: UUID,
        reference_id: UUID,
        run_id: UUID | None = None,
    ) -> bytes:
        location = await self._gateway.get_location(
            tenant_id=tenant_id,
            reference_id=reference_id,
            run_id=run_id,
        )
        if location is None:
            raise ArtifactReferenceNotFoundError
        return await self._store.get_bytes(location.blob_sha256)

    async def delete_reference(
        self,
        *,
        tenant_id: UUID,
        reference_id: UUID,
        run_id: UUID | None = None,
    ) -> None:
        deleted = await self._gateway.delete_reference(
            tenant_id=tenant_id,
            reference_id=reference_id,
            run_id=run_id,
        )
        if deleted is None:
            raise ArtifactReferenceNotFoundError
        if not deleted.last_reference:
            return
        await self._store.delete_bytes(deleted.blob_sha256)

    async def collect_orphan_blob(self, *, sha256: str) -> bool:
        if not await self._gateway.claim_unreferenced_blob(sha256=sha256):
            return False
        return await self._store.delete_bytes(sha256)
