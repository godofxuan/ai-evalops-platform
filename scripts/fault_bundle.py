import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.fault_matrix_evidence import FaultEvidenceError, validate_fault_matrix

MANIFEST_NAME = "manifest.json"


def finalize_fault_bundle(bundle_directory: Path) -> dict[str, Any]:
    manifest_path = bundle_directory / MANIFEST_NAME
    if manifest_path.exists():
        raise FaultEvidenceError("refusing to overwrite an existing fault manifest")
    report = _read_object(bundle_directory / "report.json")
    if report.get("status") != "verified":
        raise FaultEvidenceError("fault report is not verified")
    configuration = report.get("configuration")
    if not isinstance(configuration, dict):
        raise FaultEvidenceError("fault report configuration is missing")
    repetitions = _positive_int(configuration.get("repetitions"), "repetitions")
    source_commit = configuration.get("source_commit")
    if not isinstance(source_commit, str) or not source_commit:
        raise FaultEvidenceError("fault report source commit is missing")
    results = report.get("results")
    if not isinstance(results, list) or not all(isinstance(item, dict) for item in results):
        raise FaultEvidenceError("fault report results are malformed")
    validate_fault_matrix(results, repetitions=repetitions)

    files = [_file_record(path, root=bundle_directory) for path in _payload_paths(bundle_directory)]
    if not files:
        raise FaultEvidenceError("fault bundle contains no payload files")
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "status": "complete",
        "run_id": bundle_directory.name,
        "source_commit": source_commit,
        "repetitions": repetitions,
        "scenario_count": len(results),
        "files": files,
    }
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(manifest_path)
    validate_fault_bundle(bundle_directory)
    return manifest


def validate_fault_bundle(bundle_directory: Path) -> dict[str, Any]:
    manifest = _read_object(bundle_directory / MANIFEST_NAME)
    if manifest.get("status") != "complete":
        raise FaultEvidenceError("fault manifest is not complete")
    expected_files = manifest.get("files")
    if not isinstance(expected_files, list):
        raise FaultEvidenceError("fault manifest file list is malformed")
    actual_paths = _payload_paths(bundle_directory)
    expected_paths = {
        str(record.get("path")) for record in expected_files if isinstance(record, dict)
    }
    actual_relative_paths = {path.relative_to(bundle_directory).as_posix() for path in actual_paths}
    if expected_paths != actual_relative_paths or len(expected_files) != len(expected_paths):
        raise FaultEvidenceError("fault bundle payload file set changed")
    for record in expected_files:
        if not isinstance(record, dict):
            raise FaultEvidenceError("fault manifest contains a malformed file record")
        relative_path = str(record["path"])
        path = bundle_directory / relative_path
        actual = _file_record(path, root=bundle_directory)
        if actual != record:
            raise FaultEvidenceError(f"fault bundle SHA-256 validation failed: {relative_path}")

    report = _read_object(bundle_directory / "report.json")
    configuration = report.get("configuration")
    results = report.get("results")
    if not isinstance(configuration, dict) or not isinstance(results, list):
        raise FaultEvidenceError("fault report structure changed")
    repetitions = _positive_int(configuration.get("repetitions"), "repetitions")
    validate_fault_matrix(results, repetitions=repetitions)
    if manifest.get("source_commit") != configuration.get("source_commit"):
        raise FaultEvidenceError("fault manifest source commit does not match report")
    return manifest


def _payload_paths(bundle_directory: Path) -> list[Path]:
    return [
        path
        for path in sorted(bundle_directory.rglob("*"))
        if path.is_file() and path.name not in {MANIFEST_NAME, f"{MANIFEST_NAME}.tmp"}
    ]


def _file_record(path: Path, *, root: Path) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FaultEvidenceError(f"could not read fault evidence: {path.name}") from error
    if not isinstance(value, dict):
        raise FaultEvidenceError(f"fault evidence is not an object: {path.name}")
    return value


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise FaultEvidenceError(f"{name} must be a positive integer")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Finalize or validate a fault evidence bundle.")
    parser.add_argument("operation", choices=("finalize", "validate"))
    parser.add_argument("bundle_directory", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.operation == "finalize":
        manifest = finalize_fault_bundle(args.bundle_directory)
    else:
        manifest = validate_fault_bundle(args.bundle_directory)
    print(
        f"fault bundle {manifest['status']}: {manifest['scenario_count']} scenarios, "
        f"{len(manifest['files'])} payload files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
