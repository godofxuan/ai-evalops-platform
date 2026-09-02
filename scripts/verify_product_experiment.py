"""Verify every product-experiment file against its manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class ProductManifestError(ValueError):
    """A product result manifest is malformed, incomplete, or stale."""


def verify_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProductManifestError("manifest is unreadable") from error
    if not isinstance(manifest, dict):
        raise ProductManifestError("manifest must be an object")
    if manifest.get("schema_version") != "evalops.product-experiment-manifest/1.0":
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
        artifact_path = path.parent / filename
        try:
            payload = artifact_path.read_bytes()
        except OSError as error:
            raise ProductManifestError(f"manifest file missing: {filename}") from error
        if len(payload) != entry.get("byte_size"):
            raise ProductManifestError(f"manifest file size mismatch: {filename}")
        if hashlib.sha256(payload).hexdigest() != entry.get("sha256"):
            raise ProductManifestError(f"manifest file digest mismatch: {filename}")
    required = {"result.json", "report.html"}
    if not required.issubset(seen):
        raise ProductManifestError("manifest omits a required product artifact")
    result = json.loads((path.parent / "result.json").read_text(encoding="utf-8"))
    for field in ("experiment_id", "status", "dataset_sha256", "evalops_sha"):
        if result.get(field) != manifest.get(field):
            raise ProductManifestError(f"manifest/result identity mismatch: {field}")
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
