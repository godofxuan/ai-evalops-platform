"""Validate retained captures for offline recovery; never rerun a target."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.core.strict_json import decode_evidence_json
from app.product_experiments.learning_workflow import _recompute_local, read_file
from app.product_experiments.public_summary import PublicExperimentSummary
from app.product_experiments.runner import ProductExperimentResult, parse_product_dataset


def load_capture(
    directory: Path,
) -> tuple[ProductExperimentResult | PublicExperimentSummary, bytes | None]:
    status = decode_evidence_json(read_file(directory / "capture-status.json", 64 * 1024))
    required = {
        "schema_version",
        "status",
        "visibility",
        "original_quality_status",
        "files",
        "verification_scope",
        "source_provenance_verified",
        "formal_quality_claim_allowed",
        "production_ready",
    }
    if (
        not isinstance(status, dict)
        or set(status) != required
        or status["schema_version"] != "evalops.workflow-capture/1.0"
        or status["status"] != "CAPTURED_NOT_EXPORTED"
        or status["verification_scope"] != "CAPTURE_ONLY_NOT_VERIFIED"
        or status["visibility"] not in {"PRIVATE", "PUBLIC"}
        or any(
            status[key] is not False
            for key in (
                "source_provenance_verified",
                "formal_quality_claim_allowed",
                "production_ready",
            )
        )
    ):
        raise ValueError("capture_status_invalid")
    private = status["visibility"] == "PRIVATE"
    expected = (
        {"captured-result.json", "captured-dataset.json"}
        if private
        else {"captured-public-result.json"}
    )
    if not isinstance(status["files"], dict) or set(status["files"]) != expected:
        raise ValueError("capture_files_invalid")
    data = {}
    for name in expected:
        payload = read_file(
            directory / name,
            10 * 1024 * 1024 if name == "captured-dataset.json" else 256 * 1024 * 1024,
        )
        if status["files"][name] != {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "byte_size": len(payload),
        }:
            raise ValueError("capture_file_hash_mismatch")
        decode_evidence_json(payload)
        data[name] = payload
    if private:
        result = ProductExperimentResult.model_validate_json(data["captured-result.json"])
        raw = data["captured-dataset.json"]
        cases = parse_product_dataset(raw, expected_sha256=result.dataset_sha256)
        _recompute_local(result, cases)
        if result.status != status["original_quality_status"]:
            raise ValueError("capture_status_mismatch")
        return result, raw
    public = PublicExperimentSummary.model_validate_json(data["captured-public-result.json"])
    if public.status != status["original_quality_status"]:
        raise ValueError("capture_status_mismatch")
    return public, None
