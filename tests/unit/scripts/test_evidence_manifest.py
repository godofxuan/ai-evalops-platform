import json
from pathlib import Path

import pytest

import scripts.verify_final_evidence_manifest as evidence_manifest
from scripts.verify_final_evidence_manifest import (
    MANIFEST_PATH,
    verify_cross_repository_manifest,
    verify_manifest,
)


def test_final_evidence_manifest_rehashes_all_scoped_files() -> None:
    verify_manifest()
    verify_cross_repository_manifest()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    integrity = manifest["file_integrity"]
    entries = integrity["files"]

    assert integrity["self_digest_excluded"] is True
    assert entries
    assert all(len(entry["sha256"]) == 64 for entry in entries)
    assert all(entry["byte_size"] > 0 for entry in entries)
    assert all(len(entry["source_sha"]) == 40 for entry in entries)
    paths = {entry["path"] for entry in entries}
    assert "docs/review/FINAL_EVIDENCE_MANIFEST.json" not in paths
    assert "docs/review/FINAL_CROSS_REPO_EVIDENCE_MANIFEST.json" in paths
    assert "docs/review/FINAL_CROSS_REPO_REVIEW_ENTRY.md" in paths


def test_historical_readme_tamper_and_missing_snapshot_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = tmp_path / "historical-readme.md"
    monkeypatch.setattr(evidence_manifest, "HISTORICAL_README_PATH", snapshot)
    with pytest.raises(FileNotFoundError):
        verify_manifest()
    snapshot.write_bytes(b"tampered historical README")
    with pytest.raises(SystemExit, match="evidence size drift: README.md"):
        verify_manifest()
