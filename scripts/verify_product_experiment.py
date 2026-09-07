"""Verify every product-experiment file against its manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.product_experiments.public_summary import PublicExperimentSummary
from app.product_experiments.report import render_experiment_html
from app.product_experiments.runner import ProductExperimentResult


class ProductManifestError(ValueError):
    """A product result manifest is malformed, incomplete, or stale."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProductManifestError("duplicate JSON field")
        result[key] = value
    return result


def _decode(payload: bytes | str) -> Any:
    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    depth = 0
    quoted = False
    escaped = False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            if depth > 64:
                raise ProductManifestError("JSON depth limit exceeded")
        elif character in "]}":
            depth -= 1
    return json.loads(text, object_pairs_hook=_unique_object)


def _read_bounded(path: Path, limit: int) -> bytes:
    if path.is_symlink() or path.resolve().parent != path.parent.resolve():
        raise ProductManifestError("unsafe symlink artifact")
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ProductManifestError("product artifact exceeds size limit")
    return payload


def verify_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = _decode(_read_bounded(path, 1024 * 1024))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProductManifestError("manifest is unreadable") from error
    if not isinstance(manifest, dict):
        raise ProductManifestError("manifest must be an object")
    if manifest.get("schema_version") == "evalops.public-experiment-manifest/1.0":
        return _verify_public_manifest(path, manifest)
    if manifest.get("schema_version") not in {
        "evalops.product-experiment-manifest/1.0",
        "evalops.product-experiment-manifest/2.0",
    }:
        raise ProductManifestError("unsupported manifest schema")
    if manifest.get("formal_quality_claim_allowed") is not False:
        raise ProductManifestError("manifest must preserve formal quality claim boundary")
    if manifest.get("production_ready") is not False:
        raise ProductManifestError("manifest must preserve production boundary")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ProductManifestError("manifest has no files")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ProductManifestError("manifest file entry must be an object")
        filename = entry.get("path")
        if (
            not isinstance(filename, str)
            or not filename
            or Path(filename).name != filename
            or filename in seen
        ):
            raise ProductManifestError("manifest file path is unsafe or duplicated")
        seen.add(filename)
        if filename not in {"result.json", "report.html", "baseline.json", "candidate.json"}:
            raise ProductManifestError("unsupported product artifact")
        artifact_path = path.parent / filename
        try:
            payload = _read_bounded(artifact_path, 256 * 1024 * 1024)
        except OSError as error:
            raise ProductManifestError(f"manifest file missing: {filename}") from error
        if len(payload) != entry.get("byte_size"):
            raise ProductManifestError(f"manifest file size mismatch: {filename}")
        if hashlib.sha256(payload).hexdigest() != entry.get("sha256"):
            raise ProductManifestError(f"manifest file digest mismatch: {filename}")
    required = {"result.json", "report.html"}
    if not required.issubset(seen):
        raise ProductManifestError("manifest omits a required product artifact")
    try:
        result_payload = _read_bounded(path.parent / "result.json", 256 * 1024 * 1024)
        result = _decode(result_payload)
        ProductExperimentResult.model_validate_json(result_payload)
    except (ValueError, ValidationError, OSError):
        raise ProductManifestError("result schema is invalid") from None
    if result["schema_version"].rsplit("/", 1)[1] != manifest["schema_version"].rsplit("/", 1)[1]:
        raise ProductManifestError("manifest/result schema versions differ")
    if result.get("status") in {
        "DEMO_PASS",
        "DEMO_FAIL",
        "AUTOMATED_PASS_HUMAN_REVIEW_PENDING",
        "AUTOMATED_FAIL",
    }:
        if not {"baseline.json", "candidate.json"}.issubset(seen):
            raise ProductManifestError("completed experiment omits required arm artifacts")
        arms = result.get("arms", {})
        if set(arms) != {"baseline", "candidate"}:
            raise ProductManifestError("completed experiment must have exactly two arms")
        count = result.get("case_count")
        if type(count) is not int or count < 2:
            raise ProductManifestError("invalid completed case count")
        paired_ids: set[str] | None = None
        paired_inputs: dict[str, tuple[str, str]] | None = None
        for label, arm in arms.items():
            if arm.get("arm") != label:
                raise ProductManifestError("arm role does not match its label")
            if arm.get("dataset_sha256") != result.get("dataset_sha256"):
                raise ProductManifestError("arm/result dataset identity mismatch")
            source = result.get("source_identities", {}).get(label, {})
            if arm.get("source_sha") != source.get("sha"):
                raise ProductManifestError("arm/result source identity mismatch")
            cases = arm.get("cases", [])
            identities = {case["case_id"] for case in cases}
            if len(cases) != count or len(identities) != count:
                raise ProductManifestError("arm case count or uniqueness mismatch")
            if paired_ids is not None and paired_ids != identities:
                raise ProductManifestError("arm case set mismatch")
            inputs = {case["case_id"]: (case["prompt"], case["category"]) for case in cases}
            if paired_inputs is not None and paired_inputs != inputs:
                raise ProductManifestError("paired input content or category mismatch")
            paired_inputs = inputs
            paired_ids = identities
        rows = result.get("case_comparisons", [])
        if len(rows) != count or {row["case_id"] for row in rows} != paired_ids:
            raise ProductManifestError("comparison case set mismatch")
    for field in (
        "experiment_id",
        "status",
        "dataset_sha256",
        "evalops_sha",
        "source_identities",
    ):
        if result.get(field) != manifest.get(field):
            raise ProductManifestError(f"manifest/result identity mismatch: {field}")
    for label in ("baseline", "candidate"):
        filename = f"{label}.json"
        if filename in seen:
            arm = _decode(_read_bounded(path.parent / filename, 256 * 1024 * 1024))
            if arm != result.get("arms", {}).get(label):
                raise ProductManifestError(f"arm/result content mismatch: {label}")
    return manifest


def _verify_public_manifest(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    expected_fields = {
        "schema_version",
        "export_mode",
        "experiment_id",
        "status",
        "private_result_sha256",
        "files",
        "formal_quality_claim_allowed",
        "production_ready",
    }
    if set(manifest) != expected_fields or manifest.get("export_mode") != "public":
        raise ProductManifestError("invalid public manifest schema")
    if (
        manifest["formal_quality_claim_allowed"] is not False
        or manifest["production_ready"] is not False
    ):
        raise ProductManifestError("invalid public claim boundary")
    entries = manifest["files"]
    if not isinstance(entries, list) or len(entries) != 2:
        raise ProductManifestError("public manifest requires exactly two artifacts")
    seen: set[str] = set()
    result_payload = b""
    report_payload = b""
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "byte_size"}:
            raise ProductManifestError("invalid public file entry")
        filename = entry["path"]
        if (
            not isinstance(filename, str)
            or filename not in {"result.json", "report.html"}
            or filename in seen
        ):
            raise ProductManifestError("unsafe public artifact path")
        seen.add(filename)
        try:
            payload = _read_bounded(path.parent / filename, 1024 * 1024)
        except OSError:
            raise ProductManifestError("public artifact missing") from None
        if type(entry["byte_size"]) is not int or len(payload) != entry["byte_size"]:
            raise ProductManifestError("public artifact size mismatch")
        if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
            raise ProductManifestError("public artifact digest mismatch")
        if filename == "result.json":
            result_payload = payload
        else:
            report_payload = payload
    try:
        _decode(result_payload)
        summary = PublicExperimentSummary.model_validate_json(result_payload)
    except (ValueError, UnicodeError):
        raise ProductManifestError("public summary schema invalid") from None
    for field in ("experiment_id", "status", "private_result_sha256"):
        if manifest[field] != getattr(summary, field):
            raise ProductManifestError("public manifest/result identity mismatch")
    expected_report = render_experiment_html(summary.model_dump(mode="json")).encode("utf-8")
    if report_payload != expected_report:
        raise ProductManifestError("public report is not the schema-derived projection")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        manifest = verify_manifest(args.manifest)
    except ProductManifestError as error:
        print(f"product experiment verification failed: {error}")
        return 1
    print(
        f"product experiment verified: {manifest['experiment_id']} "
        f"status={manifest['status']} files={len(manifest['files'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
