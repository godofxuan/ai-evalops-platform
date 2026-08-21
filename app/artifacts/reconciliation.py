"""Lease-based reconciliation for objects not committed to PostgreSQL."""

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.artifacts.lifecycle import ArtifactBlobStatus
from app.artifacts.storage import DeletableArtifactStore, StoredObjectInfo
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import ArtifactBlob, ArtifactReconciliationEvent, ArtifactReference


@dataclass(frozen=True, slots=True)
class ReconciliationItem:
    sha256: str
    last_modified: str
    status: str
    deleted: bool


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    dry_run: bool
    grace_period_seconds: int
    scanned_count: int
    eligible_count: int
    items: tuple[ReconciliationItem, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _DeletionClaim:
    token: UUID
    item: StoredObjectInfo


class ArtifactReconciler:
    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        store: DeletableArtifactStore,
        *,
        now: Callable[[], datetime] | None = None,
        candidate_observer: Callable[[str], Awaitable[None]] | None = None,
        claimed_observer: Callable[[str], Awaitable[None]] | None = None,
        finalize_observer: Callable[[str], Awaitable[None]] | None = None,
        lease_duration: timedelta = timedelta(minutes=5),
    ) -> None:
        if lease_duration.total_seconds() <= 0:
            raise ValueError("lease_duration must be positive")
        self._session_factory = session_factory
        self._store = store
        self._now = now or (lambda: datetime.now(UTC))
        self._candidate_observer = candidate_observer
        self._claimed_observer = claimed_observer
        self._finalize_observer = finalize_observer
        self._lease_duration = lease_duration

    async def reconcile(
        self, *, grace_period: timedelta, dry_run: bool = True
    ) -> ReconciliationReport:
        if grace_period.total_seconds() < 0:
            raise ValueError("grace_period must not be negative")
        objects = await self._store.list_objects()
        if not dry_run:
            await self._reconcile_missing_objects({item.sha256 for item in objects})
        cutoff = self._now() - grace_period
        eligible = [item for item in objects if item.last_modified <= cutoff]
        results: list[ReconciliationItem] = []
        for item in eligible:
            if await self._is_referenced(item.sha256):
                results.append(self._result(item, "referenced"))
                continue
            if self._candidate_observer is not None:
                await self._candidate_observer(item.sha256)
            if dry_run:
                await self._audit(item.sha256, "candidate", "dry_run", dry_run=True)
                results.append(self._result(item, "candidate"))
                continue
            claim, blocked = await self._claim_deletion(item)
            if claim is None:
                results.append(self._result(item, blocked))
                continue
            if self._claimed_observer is not None:
                await self._claimed_observer(item.sha256)
            try:
                deleted = await self._store.delete_object(item)
            except Exception as error:
                await self._mark_failed(claim, type(error).__name__)
                results.append(self._result(item, "delete_failed"))
                continue
            try:
                if self._finalize_observer is not None:
                    await self._finalize_observer(item.sha256)
                status = await self._finalize(claim, deleted)
            except Exception as error:
                await self._audit(
                    item.sha256,
                    "finalize",
                    "deferred",
                    dry_run=False,
                    details={"error_type": type(error).__name__},
                )
                results.append(self._result(item, "finalize_deferred", deleted=deleted))
                continue
            results.append(self._result(item, status, deleted=deleted))
        return ReconciliationReport(
            dry_run=dry_run,
            grace_period_seconds=int(grace_period.total_seconds()),
            scanned_count=len(objects),
            eligible_count=len(eligible),
            items=tuple(results),
        )

    @staticmethod
    def _result(
        item: StoredObjectInfo, status: str, *, deleted: bool = False
    ) -> ReconciliationItem:
        return ReconciliationItem(
            sha256=item.sha256,
            last_modified=item.last_modified.isoformat(),
            status=status,
            deleted=deleted,
        )

    async def _is_referenced(self, sha256: str) -> bool:
        async with self._session_factory() as session:
            return bool(
                await session.scalar(
                    select(exists().where(ArtifactReference.blob_sha256 == sha256))
                )
            )

    async def _claim_deletion(self, item: StoredObjectInfo) -> tuple[_DeletionClaim | None, str]:
        now = self._now()
        token = uuid4()
        async with self._session_factory.begin() as session:
            blob = (
                await session.execute(
                    select(ArtifactBlob).where(ArtifactBlob.sha256 == item.sha256).with_for_update()
                )
            ).scalar_one_or_none()
            if blob is None:
                blob = ArtifactBlob(
                    sha256=item.sha256,
                    byte_size=item.size_bytes,
                    storage_path=item.storage_path,
                )
                session.add(blob)
                await session.flush()
            if await self._has_reference(session, item.sha256):
                blob.lifecycle_status = ArtifactBlobStatus.ACTIVE
                blob.deletion_token = None
                blob.deletion_lease_expires_at = None
                self._add_audit(session, item.sha256, "delete", "recheck_blocked")
                return None, "recheck_blocked"
            if (
                blob.lifecycle_status == ArtifactBlobStatus.DELETE_PENDING
                and blob.deletion_lease_expires_at is not None
                and blob.deletion_lease_expires_at > now
            ):
                return None, "already_claimed"
            blob.byte_size = item.size_bytes
            blob.storage_path = item.storage_path
            blob.lifecycle_status = ArtifactBlobStatus.DELETE_PENDING
            blob.deletion_token = token
            blob.deletion_lease_expires_at = now + self._lease_duration
            blob.delete_attempt_count += 1
            blob.deletion_error_code = None
            blob.deleted_at = None
            self._add_audit(
                session,
                item.sha256,
                "claim",
                "delete_pending",
                details={"token": str(token), "attempt": blob.delete_attempt_count},
            )
        return _DeletionClaim(token, item), "delete_pending"

    async def _mark_failed(self, claim: _DeletionClaim, error_code: str) -> None:
        async with self._session_factory.begin() as session:
            blob = await self._locked_blob(session, claim.item.sha256)
            if blob is not None and blob.deletion_token == claim.token:
                blob.lifecycle_status = ArtifactBlobStatus.DELETE_FAILED
                blob.deletion_error_code = error_code
                blob.deletion_lease_expires_at = None
                self._add_audit(
                    session,
                    claim.item.sha256,
                    "delete",
                    "failed",
                    details={"error_type": error_code, "token": str(claim.token)},
                )

    async def _finalize(self, claim: _DeletionClaim, deleted: bool) -> str:
        status = "deleted" if deleted else "already_absent"
        async with self._session_factory.begin() as session:
            blob = await self._locked_blob(session, claim.item.sha256)
            if blob is None or blob.deletion_token != claim.token:
                return "claim_superseded"
            if await self._has_reference(session, claim.item.sha256):
                blob.lifecycle_status = ArtifactBlobStatus.RESTORE_REQUIRED
                blob.deletion_lease_expires_at = None
                self._add_audit(session, claim.item.sha256, "finalize", "restore_required")
                return "restore_required"
            blob.lifecycle_status = ArtifactBlobStatus.DELETED
            blob.deletion_lease_expires_at = None
            blob.deletion_error_code = None
            blob.deleted_at = self._now()
            self._add_audit(
                session,
                claim.item.sha256,
                "delete",
                status,
                details={"token": str(claim.token)},
            )
        return status

    async def _reconcile_missing_objects(self, present: set[str]) -> None:
        async with self._session_factory.begin() as session:
            blobs = (
                await session.execute(
                    select(ArtifactBlob)
                    .where(
                        ArtifactBlob.lifecycle_status.in_(
                            (
                                ArtifactBlobStatus.ACTIVE,
                                ArtifactBlobStatus.DELETE_PENDING,
                                ArtifactBlobStatus.DELETE_FAILED,
                            )
                        )
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
            for blob in blobs:
                if blob.sha256 in present:
                    continue
                referenced = await self._has_reference(session, blob.sha256)
                if (
                    blob.lifecycle_status
                    in (ArtifactBlobStatus.DELETE_PENDING, ArtifactBlobStatus.DELETE_FAILED)
                    and not referenced
                ):
                    blob.lifecycle_status = ArtifactBlobStatus.DELETED
                    blob.deleted_at = self._now()
                    status = "missing_delete_finalized"
                else:
                    blob.lifecycle_status = ArtifactBlobStatus.RESTORE_REQUIRED
                    status = "missing_restore_required"
                blob.deletion_lease_expires_at = None
                self._add_audit(session, blob.sha256, "missing_object", status)

    @staticmethod
    async def _locked_blob(session: AsyncSession, sha256: str) -> ArtifactBlob | None:
        return (
            await session.execute(
                select(ArtifactBlob).where(ArtifactBlob.sha256 == sha256).with_for_update()
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _has_reference(session: AsyncSession, sha256: str) -> bool:
        return bool(
            await session.scalar(select(exists().where(ArtifactReference.blob_sha256 == sha256)))
        )

    @staticmethod
    def _add_audit(
        session: AsyncSession,
        sha256: str,
        action: str,
        status: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        session.add(
            ArtifactReconciliationEvent(
                blob_sha256=sha256,
                action=action,
                status=status,
                dry_run=False,
                details_json=details or {},
            )
        )

    async def _audit(
        self,
        sha256: str,
        action: str,
        status: str,
        *,
        dry_run: bool,
        details: dict[str, object] | None = None,
    ) -> None:
        async with self._session_factory.begin() as session:
            session.add(
                ArtifactReconciliationEvent(
                    blob_sha256=sha256,
                    action=action,
                    status=status,
                    dry_run=dry_run,
                    details_json=details or {},
                )
            )
