"""Public packaging CLI exercised in real isolated Git workspaces and real ZIPs."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/package_public_pilot.py"


@pytest.fixture
def package_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, root / "scripts/package_public_pilot.py")
    (root / ".gitignore").write_text("artifacts/\n", encoding="utf-8")
    (root / "PUBLIC_BENCHMARKS.md").write_text(
        "Packaging fixture only; no measured model results.\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
    for name in ("public-benchmark-20260912", "gemma-cross-family-20260912", "unselected"):
        directory = root / "artifacts" / name
        directory.mkdir(parents=True)
        (directory / "result.json").write_text(json.dumps({"fixture": name}), encoding="utf-8")
    return root


def run_package(
    root: Path,
    *evidence: Path,
    output: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    destination = output or root / "artifacts/deliveries/test.zip"
    command = [sys.executable, str(root / "scripts/package_public_pilot.py")]
    for directory in evidence:
        command.extend(["--evidence-dir", str(directory)])
    command.extend(["--output", str(destination)])
    return subprocess.run(command, cwd=root, capture_output=True, text=True), destination


def assert_zip_hashes(archive: zipfile.ZipFile) -> dict[str, object]:
    manifest = json.loads(archive.read("DELIVERY_MANIFEST.json"))
    assert archive.testzip() is None
    assert set(archive.namelist()) == {*manifest["files"], "DELIVERY_MANIFEST.json"}
    for name, description in manifest["files"].items():
        raw = archive.read(name)
        assert hashlib.sha256(raw).hexdigest() == description["sha256"]
        assert len(raw) == description["bytes"]
    return manifest


def test_single_evidence_directory_keeps_existing_archive_layout(package_workspace: Path) -> None:
    evidence = package_workspace / "artifacts/public-benchmark-20260912"
    completed, output = run_package(package_workspace, evidence)
    assert completed.returncode == 0, completed.stderr
    with zipfile.ZipFile(output) as archive:
        assert archive.read("evidence/result.json") == (evidence / "result.json").read_bytes()
        assert "source/PUBLIC_BENCHMARKS.md" in archive.namelist()
        assert_zip_hashes(archive)


def test_two_explicit_roots_preserve_both_and_exclude_unselected_evidence(
    package_workspace: Path,
) -> None:
    names = ("public-benchmark-20260912", "gemma-cross-family-20260912")
    roots = [package_workspace / "artifacts" / name for name in names]
    completed, output = run_package(package_workspace, *roots)
    assert completed.returncode == 0, completed.stderr
    with zipfile.ZipFile(output) as archive:
        for name, directory in zip(names, roots, strict=True):
            assert (
                archive.read(f"evidence/{name}/result.json")
                == (directory / "result.json").read_bytes()
            )
        assert not any("unselected" in name for name in archive.namelist())
        manifest = assert_zip_hashes(archive)
        assert manifest["evidence_roots"] == [
            {
                "source_artifacts_relative": name,
                "archive_prefix": f"evidence/{name}",
                "restore_to": f"source/artifacts/{name}",
            }
            for name in names
        ]


def test_final_report_extra_log_is_rejected_before_zip_creation(package_workspace: Path) -> None:
    evidence = package_workspace / "artifacts/public-benchmark-20260912"
    report = evidence / "bfcl-report-final"
    report.mkdir()
    for name in ("report.json", "per-case.json", "manifest.json", "verify.log"):
        (report / name).write_text("{}", encoding="utf-8")
    completed, output = run_package(package_workspace, evidence)
    assert completed.returncode != 0
    assert "unexpected_final_report_files" in completed.stderr
    assert not output.exists()


@pytest.mark.parametrize("selection", ["root", "duplicate", "overlap"])
def test_ambiguous_or_broad_evidence_selection_is_rejected(
    package_workspace: Path,
    selection: str,
) -> None:
    evidence = package_workspace / "artifacts/public-benchmark-20260912"
    nested = evidence / "nested"
    nested.mkdir()
    (nested / "fixture.txt").write_text("test", encoding="utf-8")
    candidates = {
        "root": [package_workspace / "artifacts"],
        "duplicate": [evidence, evidence],
        "overlap": [evidence, nested],
    }
    completed, output = run_package(
        package_workspace, *candidates[selection], output=package_workspace.parent / "outside.zip"
    )
    assert completed.returncode != 0
    assert "explicit_disjoint_evidence_directories_required" in completed.stderr
    assert not output.exists()


@pytest.mark.parametrize("nested_argument", [False, True])
def test_linked_evidence_root_or_ancestor_is_rejected(
    package_workspace: Path,
    nested_argument: bool,
) -> None:
    import os

    target = package_workspace / "artifacts/public-benchmark-20260912"
    (target / "nested").mkdir()
    (target / "nested" / "result.json").write_text("{}", encoding="utf-8")
    alias = package_workspace / "artifacts/linked"
    if os.name == "nt":
        command = "New-Item -ItemType Junction -Path '" + str(alias).replace("'", "''")
        command += "' -Target '" + str(target).replace("'", "''") + "' | Out-Null"
        created = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True,
        )
        if created.returncode:
            pytest.skip("Windows junction creation is unavailable")
    else:
        alias.symlink_to(target, target_is_directory=True)
    evidence = alias / "nested" if nested_argument else alias
    completed, output = run_package(package_workspace, evidence)
    assert completed.returncode != 0
    assert "linked_delivery_path" in completed.stderr
    assert not output.exists()
