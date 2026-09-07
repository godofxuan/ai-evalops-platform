"""Offline durable report verification: integrity is not provenance or a quality PASS."""

import hashlib
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.core.strict_json import decode_evidence_json
from app.product_experiments.durable_report import build_durable_report
from app.product_experiments.export_schemas import PrivateDurableReport, PublicDurableReport
from app.product_experiments.export_service import MAX_REPORT_BYTES
from app.runs.idempotency import canonical_request_hash


@dataclass(frozen=True)
class DurableReportVerification:
    report_sha256: str
    verification_scope: Literal[
        "PUBLIC_PROJECTION_ONLY", "PRIVATE_SOURCE_REQUIRED", "PRIVATE_RECOMPUTED"
    ]
    quality_status: str
    execution_id: UUID
    formal_quality_claim_allowed: Literal[False] = False
    production_ready: Literal[False] = False


def verify_durable_report(
    payload: bytes,
    *,
    raw_dataset: bytes | None = None,
    expected_sha256: str | None = None,
    experiment_id: UUID | None = None,
) -> DurableReportVerification:
    if not 0 < len(payload) <= MAX_REPORT_BYTES:
        raise ValueError("invalid_report_size")
    digest = hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("report_bytes_hash_mismatch")
    report = decode_evidence_json(payload)
    if not isinstance(report, dict):
        raise ValueError("invalid_report_object")
    scope: Literal["PUBLIC_PROJECTION_ONLY", "PRIVATE_SOURCE_REQUIRED", "PRIVATE_RECOMPUTED"]
    if report.get("schema_version") == "evalops.public-durable-report/1.0":
        public = PublicDurableReport.model_validate_json(payload)
        execution_id = public.summary.execution_id
        quality_status = public.summary.status
        scope = "PUBLIC_PROJECTION_ONLY"
    else:
        private = PrivateDurableReport.model_validate_json(payload)
        unsigned = dict(report)
        if unsigned.pop("content_sha256") != canonical_request_hash(unsigned):
            raise ValueError("report_content_hash_mismatch")
        unsigned_snapshot = dict(private.result_snapshot)
        snapshot_digest = unsigned_snapshot.pop("content_sha256", None)
        if (
            snapshot_digest != private.result_snapshot_sha256
            or snapshot_digest != canonical_request_hash(unsigned_snapshot)
        ):
            raise ValueError("report_snapshot_hash_mismatch")
        execution_id = private.result.execution_id
        if str(execution_id) != private.result_snapshot.get("experiment_id"):
            raise ValueError("report_execution_mismatch")
        quality_status = private.result.status
        scope = "PRIVATE_SOURCE_REQUIRED"
        if raw_dataset is not None:
            if not 0 < len(raw_dataset) <= 10 * 1024 * 1024:
                raise ValueError("invalid_dataset_size")
            rebuilt = build_durable_report(
                snapshot=private.result_snapshot, raw_dataset=raw_dataset
            )
            if canonical_request_hash(rebuilt) != canonical_request_hash(report):
                raise ValueError("report_recomputation_mismatch")
            scope = "PRIVATE_RECOMPUTED"
    if execution_id is None or (experiment_id is not None and experiment_id != execution_id):
        raise ValueError("report_execution_mismatch")
    return DurableReportVerification(digest, scope, quality_status, execution_id)
