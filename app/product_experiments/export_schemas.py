"""Explicit public/private export contracts; private observations never enter the default view."""

import hashlib
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.product_experiments.export_service import ExportedProductReport, encode_report
from app.product_experiments.public_summary import PublicExperimentSummary, project_public_summary
from app.product_experiments.runner import ProductExperimentResult

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PublicDurableReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["evalops.public-durable-report/1.0"] = (
        "evalops.public-durable-report/1.0"
    )
    private_report_sha256: Digest
    result_snapshot_sha256: Digest
    summary: PublicExperimentSummary


class PrivateDurableReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["evalops.durable-experiment-report/1.0"]
    aggregation_version: Literal["evalops.product-aggregation/2.0"]
    result_snapshot_sha256: Digest
    result_snapshot: dict[str, Any]
    raw_dataset_sha256: Digest
    normalized_dataset_sha256: Digest
    result: ProductExperimentResult
    content_sha256: Digest
    formal_quality_claim_allowed: Literal[False]
    production_ready: Literal[False]


def project_public_durable_report(exported: ExportedProductReport) -> PublicDurableReport:
    result = ProductExperimentResult.model_validate_json(encode_report(exported.report["result"]))
    # The summary hash addresses canonical inner result bytes; the wrapper separately pins
    # the whole published private report artifact. These two digests are not interchangeable.
    summary = project_public_summary(
        result,
        private_result_sha256=hashlib.sha256(encode_report(exported.report["result"])).hexdigest(),
    )
    return PublicDurableReport(
        private_report_sha256=exported.receipt.content_sha256,
        result_snapshot_sha256=exported.receipt.snapshot_sha256,
        summary=summary,
    )
