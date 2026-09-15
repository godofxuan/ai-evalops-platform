"""Package this public pilot's source and evidence without secrets, caches or .git."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def reject_links(path: Path) -> None:
    for candidate in (path.absolute(), *path.absolute().parents):
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError("linked_delivery_path")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in [*args.evidence_dir, args.output]:
        reject_links(path)
    evidence_roots = [path.resolve(strict=True) for path in args.evidence_dir]
    if any(path == ROOT / "artifacts" or not path.is_dir() for path in evidence_roots) or any(
        left.is_relative_to(right) or right.is_relative_to(left)
        for i, left in enumerate(evidence_roots)
        for right in evidence_roots[i + 1 :]
    ):
        raise ValueError("explicit_disjoint_evidence_directories_required")
    output = args.output.resolve()
    if output.exists() or any(output.is_relative_to(path) for path in evidence_roots):
        raise ValueError("new_output_outside_evidence_required")
    if any(not path.is_relative_to(ROOT / "artifacts") for path in evidence_roots):
        raise ValueError("evidence_must_be_in_this_worktree_artifacts")
    layouts = [
        {
            "source_artifacts_relative": path.relative_to(ROOT / "artifacts").as_posix(),
            "archive_prefix": "evidence"
            if len(evidence_roots) == 1
            else "evidence/" + path.relative_to(ROOT / "artifacts").as_posix(),
            "restore_to": "source/artifacts/" + path.relative_to(ROOT / "artifacts").as_posix(),
        }
        for path in evidence_roots
    ]
    names = (
        subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={ROOT.as_posix()}",
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .split("\0")
    )
    files = {"source/" + name: ROOT / name for name in names if name}
    for evidence, layout in zip(evidence_roots, layouts, strict=True):
        for path in evidence.rglob("*"):
            reject_links(path)
            if (
                path.is_dir()
                and path.name.endswith("-report-final")
                and {item.name for item in path.iterdir()}
                != {"report.json", "per-case.json", "manifest.json"}
            ):
                raise ValueError("unexpected_final_report_files")
            if path.is_file():
                relative = path.relative_to(evidence).as_posix()
                files[layout["archive_prefix"] + "/" + relative] = path
    forbidden = {".env", ".git", ".venv", "__pycache__", ".run.lock"}
    files = {
        name: path
        for name, path in files.items()
        if not any(
            part in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
            for part in path.parts
        )
    }
    for name, path in files.items():
        reject_links(path)
        if path.is_symlink() or path.is_junction() or any(part in forbidden for part in path.parts):
            raise ValueError(f"linked_or_forbidden_delivery_file:{name}")
        if path.name.startswith(".env") and path.name != ".env.example":
            raise ValueError("environment_override_must_not_be_packaged")
        if path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("oversized_delivery_member")
    manifest = {
        name: {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
        for name, path in sorted(files.items())
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            archive.write(path, name)
        archive.writestr(
            "DELIVERY_MANIFEST.json",
            json.dumps(
                {
                    "schema_version": "evalops.public-pilot-delivery/1.0",
                    "files": manifest,
                    "evidence_roots": layouts,
                    "scope": "LOCAL_PUBLIC_PILOT_NOT_OFFICIAL_LEADERBOARD_OR_PRODUCTION_ACCEPTANCE",
                    "instructions": (
                        "Read source/PUBLIC_BENCHMARKS.md. Copy each evidence_roots "
                        "archive_prefix directory's contents to its restore_to path "
                        "before running the documented offline verification commands."
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ),
        )
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("zip_integrity_failed")
        for name, record in manifest.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != record["sha256"]:
                raise ValueError("packaged_source_changed")
    print(
        json.dumps(
            {
                "output": str(output),
                "member_count": len(manifest) + 1,
                "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "bytes": output.stat().st_size,
                "zip_and_member_hashes_verified": True,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
