"""Package an audit closeout from explicit reviewed evidence, never runtime databases."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

from scripts.package_public_pilot import reject_links
from scripts.replay_cross_family_delivery import ORIGINAL_SHA256

ROOT = Path(__file__).resolve().parents[1]


def git(*arguments: str) -> str:
    return subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--original-cross-family", type=Path, required=True)
    parser.add_argument("--code-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.evidence, args.original_cross_family, args.output):
        reject_links(path)
    evidence = args.evidence.resolve(strict=True)
    output = args.output.resolve()
    if (
        not evidence.is_dir()
        or not evidence.is_relative_to(ROOT / "artifacts")
        or evidence == ROOT / "artifacts"
        or output.exists()
        or output.is_relative_to(evidence)
    ):
        raise ValueError("explicit_reviewed_evidence_and_new_external_output_required")
    if git("status", "--porcelain"):
        raise ValueError("commit_source_and_documents_before_packaging")
    if git("rev-parse", args.code_sha + "^{commit}") != args.code_sha:
        raise ValueError("exact_code_commit_required")
    changed = git("diff", "--name-only", args.code_sha, "HEAD").splitlines()
    if any(not (name.startswith("docs/") or name == "README.md") for name in changed):
        raise ValueError("doc_head_must_not_change_code")
    original = args.original_cross_family.resolve(strict=True)
    if hashlib.sha256(original.read_bytes()).hexdigest() != ORIGINAL_SHA256:
        raise ValueError("original_cross_family_digest_mismatch")
    names = git("ls-files", "-z").split("\0")
    files = {"source/" + name: ROOT / name for name in names if name}
    for path in evidence.rglob("*"):
        reject_links(path)
        if path.is_file():
            files["evidence/" + path.relative_to(evidence).as_posix()] = path
    files["original/AI_EvalOps_Cross_Family_20260913.zip"] = original
    forbidden = {".git", ".venv", "__pycache__", "runtime", "pgdata", "pg18"}
    for name, path in files.items():
        reject_links(path)
        if any(part in forbidden for part in Path(name).parts):
            raise ValueError(f"forbidden_member:{name}")
        if path.name.startswith(".env") and path.name != ".env.example":
            raise ValueError("environment_override_not_allowed")
        if path.suffix.lower() in {".dump", ".sqlite", ".db", ".exe", ".dll"}:
            raise ValueError(f"runtime_or_database_member:{name}")
        if path.stat().st_size > 128 * 1024 * 1024:
            raise ValueError("oversized_member")
    records = {
        name: {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for name, path in sorted(files.items())
    }
    manifest = {
        "schema_version": "evalops.audit-closeout-delivery/1.0",
        "code_sha": args.code_sha,
        "doc_sha": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "scope": "LOCAL_ENGINEERING_VALIDATION_AND_HISTORICAL_MODEL_REPLAY",
        "new_model_calls": 0,
        "production_ready": False,
        "formal_ab_complete": False,
        "files": records,
        "instructions": (
            "Read source/docs/reviews/audit-remediation-20260915/CLOSEOUT_RESULTS.md and "
            "DEMO_GUIDE.md. evidence/ contains reviewed synthetic fixtures and test logs only; "
            "original/ holds the unchanged pinned public Cross Family ZIP. No database runtime "
            "or dump is included. Hash integrity does not certify provenance."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            archive.write(path, name)
        archive.writestr(
            "DELIVERY_MANIFEST.json",
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        )
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None or len(archive.infolist()) != len(records) + 1:
            raise ValueError("zip_integrity_failed")
        for name, record in records.items():
            payload = archive.read(name)
            if (
                len(payload) != record["bytes"]
                or hashlib.sha256(payload).hexdigest() != record["sha256"]
            ):
                raise ValueError("packaged_file_changed")
    receipt = {
        "zip": str(output),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "bytes": output.stat().st_size,
        "members_verified": len(records) + 1,
        "code_sha": manifest["code_sha"],
        "doc_sha": manifest["doc_sha"],
        "status": "DELIVERY_BYTES_VERIFIED",
    }
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
