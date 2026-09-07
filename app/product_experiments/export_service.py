"""Idempotent private report publication; public output must use an explicit projection."""

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.artifacts.service import ArtifactAccessService
from app.artifacts.storage import ArtifactStore, StoredArtifact
from app.auth.principals import Principal
from app.core.strict_json import decode_evidence_json
from app.product_experiments.durable_report import build_durable_report
from app.product_experiments.report_persistence import PublishedProductReport
from app.product_experiments.result_snapshot import ResultSnapshotIntegrityError
from app.product_experiments.runner import ProductExperimentResult
from app.runs.idempotency import canonical_request_hash
from app.runs.service import RunNotFoundError

MAX_REPORT_BYTES = 512 * 1024 * 1024


class ResultReader(Protocol):
    async def read(self, *, tenant_id: UUID, experiment_id: UUID) -> dict[str, Any] | None: ...


class ReportRepository(Protocol):
    async def get(
        self, *, tenant_id: UUID, experiment_id: UUID
    ) -> PublishedProductReport | None: ...

    async def publish(
        self, *, principal: Principal, snapshot: dict[str, Any], stored: StoredArtifact
    ) -> PublishedProductReport: ...


@dataclass(frozen=True, slots=True)
class ExportedProductReport:
    receipt: PublishedProductReport
    payload: bytes
    report: dict[str, Any]


def encode_report(value: dict[str, Any]) -> bytes:
    payload = (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        + "\n"
    ).encode("utf-8")
    if len(payload) > MAX_REPORT_BYTES:
        raise ResultSnapshotIntegrityError("report exceeds export byte limit")
    # Validate the actual serialized envelope before any blob or metadata publication.
    # Nested observations acquire additional depth inside the durable report wrapper.
    decode_evidence_json(payload)
    return payload


def _read_published(payload: bytes, receipt: PublishedProductReport) -> dict[str, Any]:
    if (
        len(payload) > MAX_REPORT_BYTES
        or hashlib.sha256(payload).hexdigest() != receipt.content_sha256
    ):
        raise ResultSnapshotIntegrityError("published report bytes do not match receipt")
    report = decode_evidence_json(payload)
    if (
        not isinstance(report, dict)
        or report.get("schema_version") != "evalops.durable-experiment-report/1.0"
    ):
        raise ResultSnapshotIntegrityError("unsupported published report")
    unsigned = dict(report)
    digest = unsigned.pop("content_sha256", None)
    if (
        digest != canonical_request_hash(unsigned)
        or report.get("result_snapshot_sha256") != receipt.snapshot_sha256
    ):
        raise ResultSnapshotIntegrityError("published report binding mismatch")
    result = ProductExperimentResult.model_validate_json(
        json.dumps(report["result"], allow_nan=False)
    )
    if (
        result.execution_id != receipt.experiment_id
        or report.get("formal_quality_claim_allowed") is not False
        or report.get("production_ready") is not False
    ):
        raise ResultSnapshotIntegrityError("published report identity or boundary mismatch")
    return report


async def _offload[T](operation: Callable[[], T]) -> T:
    task = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Do not release the admission slot while an uncancellable CPU thread is still running.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            task.exception()  # Consume errors; preserve the caller's cancellation.
        raise


class ProductReportExporter:
    def __init__(
        self,
        *,
        reader: ResultReader,
        repository: ReportRepository,
        artifact_access: ArtifactAccessService,
        artifact_store: ArtifactStore,
    ) -> None:
        self._reader = reader
        self._repository = repository
        self._artifact_access = artifact_access
        self._artifact_store = artifact_store
        self._capacity = asyncio.Semaphore(2)

    async def export(self, *, principal: Principal, experiment_id: UUID) -> ExportedProductReport:
        # Per-process admission, not a deployment-wide memory/CPU guarantee.
        async with self._capacity:
            receipt = await self._repository.get(
                tenant_id=principal.tenant_id, experiment_id=experiment_id
            )
            if receipt is None:
                snapshot = await self._reader.read(
                    tenant_id=principal.tenant_id, experiment_id=experiment_id
                )
                if snapshot is None:
                    raise RunNotFoundError
                if snapshot.get("tenant_id") != str(principal.tenant_id) or snapshot.get(
                    "experiment_id"
                ) != str(experiment_id):
                    raise ResultSnapshotIntegrityError("export source ownership mismatch")
                source_id = snapshot.get("source_artifact_reference_id")
                if source_id is None:
                    raise ResultSnapshotIntegrityError("raw experiment source was not retained")
                raw = await self._artifact_access.read_bytes(
                    tenant_id=principal.tenant_id, reference_id=UUID(source_id)
                )
                report = await _offload(
                    lambda: build_durable_report(snapshot=snapshot, raw_dataset=raw)
                )
                payload = await _offload(lambda: encode_report(report))
                stored = await self._artifact_store.put_bytes(payload)
                if stored.sha256 != hashlib.sha256(payload).hexdigest() or stored.size_bytes != len(
                    payload
                ):
                    raise ResultSnapshotIntegrityError("stored report identity mismatch")
                receipt = await self._repository.publish(
                    principal=principal, snapshot=snapshot, stored=stored
                )
            if receipt.tenant_id != principal.tenant_id or receipt.experiment_id != experiment_id:
                raise ResultSnapshotIntegrityError("published report ownership mismatch")
            payload = await self._artifact_access.read_bytes(
                tenant_id=principal.tenant_id,
                reference_id=receipt.artifact_reference_id,
                run_id=receipt.baseline_run_id,
            )
            report = await _offload(lambda: _read_published(payload, receipt))
            return ExportedProductReport(receipt, payload, report)
