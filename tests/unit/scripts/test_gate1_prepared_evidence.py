import json
import shutil
import subprocess
from pathlib import Path

import pytest

import scripts.gate1_prepared_evidence as prepared_evidence
import scripts.run_load_test as run_load_test
from scripts.gate1_image_evidence import compute_docker_build_context_binding
from scripts.run_load_test import main as load_main

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _fake_local_image_binding(**kwargs: object) -> dict[str, object]:
    repository = Path(kwargs["repository"])
    source_commit = str(kwargs["source_commit"])
    dockerfile_path = Path(kwargs["dockerfile_path"])
    dockerignore_path = Path(kwargs["dockerignore_path"])
    dockerfile_sha256 = prepared_evidence.sha256_file(dockerfile_path)
    build_context = compute_docker_build_context_binding(
        repository=repository,
        dockerignore_path=dockerignore_path,
    )
    context_sha256 = str(build_context["sha256"])
    created = "2026-07-30T00:00:00Z"
    source = "https://github.com/godofxuan/ai-evalops-platform"
    return {
        "identity_kind": "LOCAL_IMAGE_ID",
        "verification": "LOCAL_IMAGE_ID_VERIFIED",
        "repository": "ai-evalops-platform",
        "tag": "phase9",
        "reference": "ai-evalops-platform:phase9",
        "immutable_id": f"sha256:{'a' * 64}",
        "registry_digest": None,
        "compose_project": "ai-evalops-platform",
        "source_commit": source_commit,
        "source": source,
        "dockerfile_sha256": dockerfile_sha256,
        "build_context": build_context,
        "build": {"created": created},
        "runtime": {
            "python": "3.12.13",
            "os": "linux",
            "architecture": "amd64",
        },
        "labels": {
            "org.opencontainers.image.revision": source_commit,
            "org.opencontainers.image.source": source,
            "org.opencontainers.image.created": created,
            "io.ai-evalops.dockerfile.sha256": dockerfile_sha256,
            "io.ai-evalops.build-context.sha256": context_sha256,
            "io.ai-evalops.python.version": "3.12.13",
        },
    }


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repository}",
            "-C",
            str(repository),
            *arguments,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _prepare_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    repository = tmp_path / "repository"
    repository.mkdir()
    source_paths = (
        "Dockerfile",
        ".dockerignore",
        ".gitignore",
        "pyproject.toml",
        "uv.lock",
        "deploy/compose.yaml",
        "scripts/worker_scaling_protocol.md",
        *prepared_evidence.KEY_EXECUTION_SCRIPT_PATHS,
    )
    for source_path in source_paths:
        destination = repository / source_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT_ROOT / source_path, destination)
    (repository / "app").mkdir()
    (repository / "app" / "__init__.py").write_text("", encoding="utf-8")
    _git(repository, "init")
    _git(repository, "config", "user.email", "gate1-tests@example.invalid")
    _git(repository, "config", "user.name", "Gate 1 Tests")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "prepared evidence source")

    output_root = tmp_path / "evidence"
    monkeypatch.chdir(repository)
    monkeypatch.setattr(
        run_load_test,
        "build_gate1_image_binding",
        _fake_local_image_binding,
    )
    assert (
        load_main(
            [
                "--prepare-only",
                "--output-root",
                str(output_root),
                "--run-id",
                "gate1-verifier",
            ]
        )
        == 0
    )
    return repository, output_root / "gate1-verifier"


def test_prepared_evidence_rejects_mutated_measurement_dataset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    measurement_path = run_directory / "dataset" / "measurement.jsonl"
    measurement_path.write_bytes(measurement_path.read_bytes() + b'{"tampered":true}\n')

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "HASH_MISMATCH"
    assert result["ready"] is False
    assert result["checks"]["measurement_hash_matches"] is False
    assert "measurement_hash_matches" in result["blockers"]
    mismatch = next(
        item
        for item in result["details"]["hash_mismatches"]
        if item["check"] == "measurement_hash_matches"
    )
    assert mismatch["path"] == "dataset/measurement.jsonl"
    assert mismatch["expected_sha256"] != mismatch["observed_sha256"]


def test_prepared_evidence_rejects_mutated_warmup_dataset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    warmup_path = run_directory / "dataset" / "warmup.jsonl"
    warmup_path.write_bytes(warmup_path.read_bytes() + b'{"tampered":true}\n')

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "HASH_MISMATCH"
    assert result["checks"]["warmup_hash_matches"] is False
    assert "warmup_hash_matches" in result["blockers"]


def test_prepared_evidence_rejects_mutated_protocol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    protocol_path = run_directory / "protocol.md"
    protocol_path.write_text("tampered protocol\n", encoding="utf-8")

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "HASH_MISMATCH"
    assert result["checks"]["protocol_hash_matches"] is False
    assert "protocol_hash_matches" in result["blockers"]


def test_prepared_evidence_rejects_mutated_compose_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    compose_path = repository / "deploy" / "compose.yaml"
    compose_path.write_text("services: {}\n", encoding="utf-8")

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=compose_path,
    )

    assert result["status"] == "HASH_MISMATCH"
    assert result["checks"]["compose_hash_matches"] is False
    assert "compose_hash_matches" in result["blockers"]


def test_prepared_evidence_rejects_mutated_arm_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    arm_plan_path = run_directory / "arm_order.json"
    arm_plan_path.write_text('{"arms":[]}\n', encoding="utf-8")

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "HASH_MISMATCH"
    assert result["checks"]["arm_plan_hash_matches"] is False
    assert "arm_plan_hash_matches" in result["blockers"]


def test_prepared_evidence_rejects_mutated_execution_script(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    script_path = repository / "scripts" / "gate1_collectors.py"
    script_path.write_text("# tampered collector\n", encoding="utf-8")

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "HASH_MISMATCH"
    assert result["checks"]["execution_script_hashes_match"] is False
    assert "execution_script_hashes_match" in result["blockers"]
    assert {
        mismatch["path"]
        for mismatch in result["details"]["hash_mismatches"]
        if mismatch["check"] == "execution_script_hashes_match"
    } == {"scripts/gate1_collectors.py"}


def test_prepared_evidence_rejects_source_commit_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    (repository / "source-marker.txt").write_text("new commit\n", encoding="utf-8")
    _git(repository, "add", "source-marker.txt")
    _git(repository, "commit", "-m", "advance source")

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "SOURCE_MISMATCH"
    assert result["ready"] is False
    assert result["checks"]["source_commit_matches"] is False
    assert "source_commit_matches" in result["blockers"]
    assert (
        result["details"]["expected_source_commit"] != result["details"]["observed_source_commit"]
    )


def test_prepared_evidence_rejects_untracked_file_entering_docker_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    (repository / "app" / "untracked_source.py").write_text(
        "UNTRACKED = True\n",
        encoding="utf-8",
    )

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "DIRTY_BUILD_CONTEXT"
    assert result["ready"] is False
    assert result["checks"]["tracked_worktree_clean"] is True
    assert result["checks"]["docker_build_context_clean"] is False
    assert result["checks"]["image_build_context_hash_matches"] is False
    assert "docker_build_context_clean" in result["blockers"]
    assert "image_build_context_hash_matches" in result["blockers"]
    assert result["details"]["dirty_build_context_paths"] == ["app/untracked_source.py"]
    context_mismatch = next(
        item
        for item in result["details"]["hash_mismatches"]
        if item["check"] == "image_build_context_hash_matches"
    )
    assert context_mismatch["path"] == "."
    assert context_mismatch["expected_sha256"] != context_mismatch["observed_sha256"]


def test_prepared_evidence_rejects_manifest_missing_required_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    manifest_path = run_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["dataset"]["measurement_sha256"]
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "MANIFEST_INVALID"
    assert result["ready"] is False
    assert result["checks"]["manifest_valid"] is False
    assert "manifest_valid" in result["blockers"]
    assert "dataset.measurement_sha256" in result["details"]["manifest_errors"]


def test_prepared_evidence_rejects_manifest_missing_image_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    manifest_path = run_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["provenance"].pop("image", None)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "MANIFEST_INVALID"
    assert result["ready"] is False
    assert result["checks"]["manifest_valid"] is False
    assert "provenance.image" in result["details"]["manifest_errors"]


def test_prepared_evidence_rejects_malformed_or_cross_unbound_image_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    manifest_path = run_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    image = manifest["provenance"]["image"]
    image["repository"] = ""
    image.pop("tag")
    image["immutable_id"] = "ai-evalops-platform:phase9"
    image["registry_digest"] = "not-a-registry-digest"
    image["source_commit"] = "c" * 40
    image["dockerfile_sha256"] = "d" * 64
    image["build_context"] = {
        "algorithm": "weak",
        "sha256": "not-a-sha256",
        "file_count": 0,
    }
    image["build"] = {}
    image["runtime"] = {}
    image["labels"] = {}
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "MANIFEST_INVALID"
    assert result["ready"] is False
    errors = set(result["details"]["manifest_errors"])
    assert {
        "provenance.image.repository",
        "provenance.image.tag",
        "provenance.image.immutable_id",
        "provenance.image.registry_digest",
        "provenance.image.source_commit",
        "provenance.image.dockerfile_sha256",
        "provenance.image.build_context.algorithm",
        "provenance.image.build_context.sha256",
        "provenance.image.build_context.file_count",
        "provenance.image.build.created",
        "provenance.image.runtime.python",
        "provenance.image.runtime.os",
        "provenance.image.runtime.architecture",
        "provenance.image.labels.org.opencontainers.image.revision",
    } <= errors


def test_prepared_evidence_rejects_unsupported_manifest_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    manifest_path = run_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 999
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "MANIFEST_INVALID"
    assert result["checks"]["manifest_valid"] is False
    assert "schema_version" in result["details"]["manifest_errors"]
    assert result["details"]["manifest_schema"] == {
        "expected": 4,
        "observed": 999,
    }


def test_prepared_evidence_rejects_mutated_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    manifest_path = run_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["configuration"]["values"]["collector_interval_seconds"] = 60.0
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "HASH_MISMATCH"
    assert result["checks"]["configuration_hash_matches"] is False
    assert "configuration_hash_matches" in result["blockers"]


def test_prepared_evidence_rejects_mutated_dockerfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    (repository / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "HASH_MISMATCH"
    assert result["checks"]["dockerfile_hash_matches"] is False
    assert "dockerfile_hash_matches" in result["blockers"]


def test_prepared_evidence_rejects_mutated_uv_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    lock_path = repository / "uv.lock"
    lock_path.write_bytes(lock_path.read_bytes() + b"\n# local dependency drift\n")

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "HASH_MISMATCH"
    assert result["ready"] is False
    assert result["checks"]["tracked_worktree_clean"] is False
    assert result["checks"]["image_build_context_hash_matches"] is False
    assert "image_build_context_hash_matches" in result["blockers"]
    assert result["details"]["tracked_dirty_paths"] == ["uv.lock"]


def test_prepared_evidence_rejects_mutated_dockerignore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    (repository / ".dockerignore").write_text(".git\n", encoding="utf-8")

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "HASH_MISMATCH"
    assert result["checks"]["dockerignore_hash_matches"] is False
    assert "dockerignore_hash_matches" in result["blockers"]


def test_prepared_evidence_rejects_mutated_dataset_hash_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    hashes_path = run_directory / "dataset" / "hashes.json"
    hashes_path.write_text('{"algorithm":"sha256"}\n', encoding="utf-8")

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "HASH_MISMATCH"
    assert result["checks"]["dataset_hashes_file_hash_matches"] is False
    assert "dataset_hashes_file_hash_matches" in result["blockers"]


def test_prepared_evidence_rejects_execution_with_different_compose_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "Dockerfile",
    )

    assert result["status"] == "HASH_MISMATCH"
    assert result["checks"]["requested_compose_matches"] is False
    assert "requested_compose_matches" in result["blockers"]


def test_prepared_evidence_rejects_git_ignored_file_entering_docker_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    (repository / ".git" / "info" / "exclude").write_text(
        "app/generated.tmp\n",
        encoding="utf-8",
    )
    (repository / "app" / "generated.tmp").write_text(
        "generated but included\n",
        encoding="utf-8",
    )

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "DIRTY_BUILD_CONTEXT"
    assert result["checks"]["docker_build_context_clean"] is False
    assert result["details"]["dirty_build_context_paths"] == ["app/generated.tmp"]


def test_prepared_evidence_applies_strict_audit_to_staged_excluded_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    staged_path = repository / "tests" / "staged_probe.py"
    staged_path.parent.mkdir()
    staged_path.write_text("STAGED = True\n", encoding="utf-8")
    _git(repository, "add", "tests/staged_probe.py")

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "DIRTY_BUILD_CONTEXT"
    assert result["ready"] is False
    assert result["checks"]["tracked_worktree_clean"] is False
    assert result["checks"]["docker_build_context_clean"] is False
    assert result["details"]["tracked_dirty_paths"] == ["tests/staged_probe.py"]
    assert result["details"]["build_context_audit_blockers"] == ["tracked_or_staged_changes"]


def test_prepared_evidence_rejects_dockerfile_specific_ignore_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    (repository / "Dockerfile.dockerignore").write_text(
        "*\n",
        encoding="utf-8",
    )

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "UNSAFE_BUILD_CONTEXT"
    assert result["ready"] is False
    assert result["checks"]["docker_build_context_clean"] is False
    assert "dockerfile_specific_ignore" in result["details"]["build_context_audit_blockers"]


def test_prepared_evidence_allows_untracked_file_excluded_from_docker_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    (repository / "docs").mkdir()
    (repository / "docs" / "local-notes.md").write_text(
        "not sent to the Docker builder\n",
        encoding="utf-8",
    )

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "READY"
    assert result["ready"] is True
    assert result["checks"]["docker_build_context_clean"] is True
    assert result["details"]["dirty_build_context_paths"] == []


def test_prepared_evidence_keeps_ignored_environment_overrides_out_of_docker_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    (repository / ".env.local").write_text(
        "DO_NOT_SEND_TO_BUILDER=secret\n",
        encoding="utf-8",
    )

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "READY"
    assert result["checks"]["docker_build_context_clean"] is True
    assert result["details"]["dirty_build_context_paths"] == []


def test_prepared_evidence_keeps_test_temp_directories_out_of_docker_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    temp_directory = repository / ".pytest-tmp-gate1-run"
    temp_directory.mkdir()
    (temp_directory / "sample.txt").write_text("temporary\n", encoding="utf-8")

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "READY"
    assert result["checks"]["docker_build_context_clean"] is True
    assert result["details"]["dirty_build_context_paths"] == []


def test_prepared_evidence_rejects_manifest_path_outside_allowed_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    manifest_path = run_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["protocol"]["path"] = "../../repository/Dockerfile"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "MANIFEST_INVALID"
    assert result["checks"]["manifest_valid"] is False
    assert "protocol.path" in result["details"]["manifest_errors"]


def test_prepared_evidence_reports_missing_dockerignore_as_hash_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    (repository / ".dockerignore").unlink()

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "HASH_MISMATCH"
    assert result["checks"]["dockerignore_hash_matches"] is False
    mismatch = next(
        item
        for item in result["details"]["hash_mismatches"]
        if item["check"] == "dockerignore_hash_matches"
    )
    assert mismatch["observed_sha256"] is None


def test_prepared_evidence_reports_unavailable_git_state_as_environment_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    (repository / ".git").rename(tmp_path / "detached-git-metadata")

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "ENVIRONMENT_BLOCKED"
    assert result["ready"] is False
    assert result["checks"]["git_repository_available"] is False
    assert "git_repository_available" in result["blockers"]


def test_prepared_evidence_keeps_historical_schema_v3_bundle_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    manifest_path = run_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 3
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "MANIFEST_INVALID"
    assert result["details"]["manifest_schema"] == {
        "expected": 4,
        "observed": 3,
    }


def test_prepared_evidence_keeps_historical_schema_v1_bundle_read_only(
    tmp_path: Path,
) -> None:
    historical_source = (
        PROJECT_ROOT / "docs" / "results" / "gate_1" / "gate1-plan-e21c31c-20260729T162352Z"
    )
    run_directory = tmp_path / historical_source.name
    shutil.copytree(historical_source, run_directory)

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=PROJECT_ROOT,
        compose_file=PROJECT_ROOT / "deploy" / "compose.yaml",
    )

    assert result["status"] == "MANIFEST_INVALID"
    assert result["details"]["manifest_schema"] == {
        "expected": 4,
        "observed": 1,
    }


def test_prepared_evidence_rejects_manifest_that_is_not_a_pristine_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, run_directory = _prepare_bundle(tmp_path, monkeypatch)
    manifest_path = run_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["formal_run_started"] = True
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = prepared_evidence.verify_prepared_evidence(
        run_directory=run_directory,
        repository=repository,
        compose_file=repository / "deploy" / "compose.yaml",
    )

    assert result["status"] == "MANIFEST_INVALID"
    assert "formal_run_started" in result["details"]["manifest_errors"]
