"""Private, recomputable calibration artifacts; declarations are never human authentication."""

import hashlib
from pathlib import Path
from typing import Any

from app.core.strict_json import decode_evidence_json
from app.product_experiments.learning_grading import CalibrationReport, calibrate_reviews
from app.product_experiments.learning_workflow import json_bytes, plain_path, read_file


def calibration_files(
    packet_bytes: bytes,
    review_bytes: bytes,
) -> tuple[dict[str, bytes], CalibrationReport]:
    packet, reviews = decode_evidence_json(packet_bytes), decode_evidence_json(review_bytes)
    if not isinstance(packet, dict) or not isinstance(reviews, list):
        raise ValueError("calibration_inputs_invalid")
    report = calibrate_reviews(packet, reviews)
    files = {
        "calibration.json": json_bytes(report.model_dump(mode="json")),
        "review-packet.json": packet_bytes,
        "reviews.json": review_bytes,
    }
    files["manifest.json"] = json_bytes(
        {
            "schema_version": "evalops.calibration-bundle/1.0",
            "visibility": "PRIVATE",
            "formal_quality_claim_allowed": False,
            "production_ready": False,
            "files": {
                name: {"sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data)}
                for name, data in files.items()
            },
        }
    )
    return files, report


def verify_calibration_bundle(directory: Path) -> dict[str, Any]:
    plain_path(directory)
    names = {"manifest.json", "calibration.json", "review-packet.json", "reviews.json"}
    if {path.name for path in directory.iterdir()} != names:
        raise ValueError("calibration_file_set_invalid")
    contents = {name: read_file(directory / name, 16 * 1024 * 1024) for name in names}
    decode_evidence_json(contents["manifest.json"])
    expected, report = calibration_files(contents["review-packet.json"], contents["reviews.json"])
    if contents != expected:
        raise ValueError("calibration_recomputation_mismatch")
    return {
        "status": "VERIFIED",
        "scope": "DESCRIPTIVE_CALIBRATION_ONLY",
        "paired_labels": report.paired_labels,
        "human_declared_pairs": report.by_evidence_kind["HUMAN_DECLARED"].paired_labels,
        "synthetic_pairs": report.by_evidence_kind["SYNTHETIC"].paired_labels,
        "human_verification": "NOT_VERIFIED",
        "formal_quality_claim_allowed": False,
        "production_ready": False,
    }
