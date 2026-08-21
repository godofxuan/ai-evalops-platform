"""Write or verify the non-recursive final evidence file manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "docs/review/FINAL_EVIDENCE_MANIFEST.json"
SCHEMA_VERSION = "ai-evalops-evidence-file/v1"
PRODUCING_COMMAND = (
    "python -m scripts.verify_final_evidence_manifest --write --source-sha <evidence-source-sha>"
)
PATTERNS = (
    "README.md",
    "PROJECT_STATUS.md",
    "docs/review/GPT_REVIEW_ENTRY.md",
    "docs/external_harness/*",
    "docs/final_hardening/*",
    "docs/handoffs/PROJECT_EVIDENCE_MAP.md",
    "docs/handoffs/RESUME_METRIC_LEDGER.md",
    "docs/handoffs/TEACHING_CODEX_HANDOFF.md",
    "docs/handoffs/RESUME_CODEX_HANDOFF.md",
    "docs/integrity_remediation/*",
)


def _evidence_paths() -> list[Path]:
    paths: set[Path] = set()
    for pattern in PATTERNS:
        paths.update(path for path in PROJECT_ROOT.glob(pattern) if path.is_file())
    paths.discard(MANIFEST_PATH)
    return sorted(paths, key=lambda path: path.relative_to(PROJECT_ROOT).as_posix())


def _canonical_repository_bytes(path: Path) -> bytes:
    """Match the LF-normalized bytes stored by Git across operating systems."""

    return path.read_bytes().replace(bytes((13, 10)), bytes((10,)))


def _entry(path: Path, *, source_sha: str, generated_at: str) -> dict[str, object]:
    content = _canonical_repository_bytes(path)
    return {
        "path": path.relative_to(PROJECT_ROOT).as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "byte_size": len(content),
        "source_sha": source_sha,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "producing_command": PRODUCING_COMMAND,
        "line_ending_normalization": "LF",
    }


def write_manifest(*, source_sha: str, generated_at: str) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["file_integrity"] = {
        "schema_version": "ai-evalops-final-evidence-files/v1",
        "self_digest_excluded": True,
        "self_digest_exclusion_reason": (
            "A manifest cannot contain its own stable byte digest without recursion."
        ),
        "generated_at": generated_at,
        "producing_command": PRODUCING_COMMAND,
        "line_ending_normalization": "LF",
        "files": [
            _entry(path, source_sha=source_sha, generated_at=generated_at)
            for path in _evidence_paths()
        ],
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + chr(10),
        encoding="utf-8",
    )


def verify_manifest() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    integrity = manifest.get("file_integrity")
    if not isinstance(integrity, dict):
        raise SystemExit("evidence manifest has no file_integrity section")
    entries = integrity.get("files")
    if not isinstance(entries, list):
        raise SystemExit("evidence manifest file_integrity.files is invalid")
    expected_paths = {path.relative_to(PROJECT_ROOT).as_posix() for path in _evidence_paths()}
    observed_paths = {entry.get("path") for entry in entries if isinstance(entry, dict)}
    if observed_paths != expected_paths:
        raise SystemExit("evidence manifest scope drifted")
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit("evidence manifest contains a non-object entry")
        path = PROJECT_ROOT / str(entry["path"])
        content = _canonical_repository_bytes(path)
        if len(content) != entry.get("byte_size"):
            raise SystemExit(f"evidence size drift: {entry['path']}")
        if hashlib.sha256(content).hexdigest() != entry.get("sha256"):
            raise SystemExit(f"evidence digest drift: {entry['path']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--source-sha")
    parser.add_argument("--generated-at")
    args = parser.parse_args()
    if args.write:
        if not args.source_sha:
            parser.error("--source-sha is required with --write")
        generated_at = args.generated_at or datetime.now(UTC).isoformat()
        write_manifest(source_sha=args.source_sha, generated_at=generated_at)
    verify_manifest()


if __name__ == "__main__":
    main()
