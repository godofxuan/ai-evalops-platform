import json

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
    assert "docs/review/FINAL_EVIDENCE_MANIFEST.json" not in {entry["path"] for entry in entries}
