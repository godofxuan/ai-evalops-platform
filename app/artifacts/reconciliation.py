"""Conservative reconciliation for object writes not committed to PostgreSQL."""

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, select

from app.artifacts.storage import DeletableArtifactStore
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    ArtifactBlob,
    ArtifactReconciliationEvent,
    ArtifactReference,
)


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


class ArtifactReconciler:
    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        store: DeletableArtifactStore,
        *,
        now: Callable[[], datetime] | None = None,
        candidate_observer: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._store = store
        self._now = now or (lambda: datetime.now(UTC))
        self._candidate_observer = candidate_observer

    async def reconcile(
        self,
        *,
        grace_period: timedelta,
        dry_run: bool = True,
    ) -> ReconciliationReport:
        if grace_period.total_seconds() < 0:
            raise ValueError("grace_period must not be negative")
        objects = await self._store.list_objects()
        cutoff = self._now() - grace_period
        eligible = [item for item in objects if item.last_modified <= cutoff]
        results: list[ReconciliationItem] = []
        for item in eligible:
            if await self._is_referenced(item.sha256):
                results.append(
                    ReconciliationItem(
                        sha256=item.sha256,
                        last_modified=item.last_modified.isoformat(),
                        status="referenced",
                        deleted=False,
                    )
                )
                continue
            if self._candidate_observer is not None:
                await self._candidate_observer(item.sha256)
            if dry_run:
                await self._audit(item.sha256, "candidate", "dry_run", dry_run=True)
                results.append(
                    ReconciliationItem(
                        sha256=item.sha256,
                        last_modified=item.last_modified.isoformat(),
                        status="candidate",
                        deleted=False,
                    )
                )
                continue
            try:
                result = await self._delete_after_recheck(item.sha256)
            except Exception as error:
                await self._audit(
                    item.sha256,
                    "delete",
                    "failed",
                    dry_run=False,
                    details={"error_type": type(error).__name__},
                )
                results.append(
                    ReconciliationItem(
                        sha256=item.sha256,
                        last_modified=item.last_modified.isoformat(),
                        status="delete_failed",
                        deleted=False,
                    )
                )
                continue
            results.append(
                ReconciliationItem(
                    sha256=item.sha256,
                    last_modified=item.last_modified.isoformat(),
                    status=result,
                    deleted=result == "deleted",
                )
            )
        return ReconciliationReport(
            dry_run=dry_run,
            grace_period_seconds=int(grace_period.total_seconds()),
            scanned_count=len(objects),
            eligible_count=len(eligible),
            items=tuple(results),
        )

    async def _is_referenced(self, sha256: str) -> bool:
        async with self._session_factory() as session:
            return bool(
                await session.scalar(
                    select(exists().where(ArtifactReference.blob_sha256 == sha256))
                )
            )

    async def _delete_after_recheck(self, sha256: str) -> str:
        async with self._session_factory.begin() as session:
            referenced = await session.scalar(
                select(exists().where(ArtifactReference.blob_sha256 == sha256))
            )
            if referenced:
                session.add(
                    ArtifactReconciliationEvent(
                        blob_sha256=sha256,
                        action="delete",
                        status="recheck_blocked",
                        dry_run=False,
                        details_json={},
                    )
                )
                return "recheck_blocked"
            deleted = await self._store.delete_bytes(sha256)
            await session.execute(
                delete(ArtifactBlob).where(
                    ArtifactBlob.sha256 == sha256,
                    ~exists().where(ArtifactReference.blob_sha256 == sha256),
                )
            )
            status = "deleted" if deleted else "already_absent"
            session.add(
                ArtifactReconciliationEvent(
                    blob_sha256=sha256,
                    action="delete",
                    status=status,
                    dry_run=False,
                    details_json={},
                )
            )
            return status

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
