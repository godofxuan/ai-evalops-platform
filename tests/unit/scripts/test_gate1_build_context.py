import subprocess
from pathlib import Path

from scripts.gate1_image_evidence import audit_gate1_build_context


def test_clean_committed_build_context_is_ready_and_fingerprinted_v2(
    clean_gate1_repository: Path,
) -> None:
    result = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=clean_gate1_repository / ".dockerignore",
    )

    assert result["status"] == "READY"
    assert result["ready"] is True
    assert result["blockers"] == []
    assert result["binding"]["algorithm"] == "docker-context-sha256-v2"
    assert result["binding"]["file_count"] > 0


def test_build_context_rejects_staged_change_even_when_docker_excludes_path(
    clean_gate1_repository: Path,
) -> None:
    staged_path = clean_gate1_repository / "tests" / "staged_probe.py"
    staged_path.parent.mkdir()
    staged_path.write_text("STAGED = True\n", encoding="utf-8")
    subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={clean_gate1_repository}",
            "-C",
            str(clean_gate1_repository),
            "add",
            "tests/staged_probe.py",
        ],
        check=True,
        capture_output=True,
    )

    result = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=clean_gate1_repository / ".dockerignore",
    )

    assert result["status"] == "DIRTY_BUILD_CONTEXT"
    assert result["ready"] is False
    assert "tracked_or_staged_changes" in result["blockers"]
    assert result["details"]["tracked_or_staged_paths"] == ["tests/staged_probe.py"]


def test_build_context_rejects_modified_uv_lock(
    clean_gate1_repository: Path,
) -> None:
    lock_path = clean_gate1_repository / "uv.lock"
    lock_path.write_bytes(lock_path.read_bytes() + b"\n# local dependency drift\n")

    result = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=clean_gate1_repository / ".dockerignore",
    )

    assert result["status"] == "DIRTY_BUILD_CONTEXT"
    assert result["ready"] is False
    assert "tracked_or_staged_changes" in result["blockers"]
    assert result["details"]["tracked_or_staged_paths"] == ["uv.lock"]


def test_root_dockerignore_pattern_does_not_hide_nested_untracked_source(
    clean_gate1_repository: Path,
) -> None:
    nested_path = clean_gate1_repository / "app" / "tests" / "untracked_source.py"
    nested_path.parent.mkdir()
    nested_path.write_text("UNTRACKED = True\n", encoding="utf-8")

    result = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=clean_gate1_repository / ".dockerignore",
    )

    assert result["status"] == "DIRTY_BUILD_CONTEXT"
    assert "unrecorded_build_context_paths" in result["blockers"]
    assert result["details"]["dirty_paths"] == ["app/tests/untracked_source.py"]


def test_build_context_reports_non_ascii_git_path_without_porcelain_quoting(
    clean_gate1_repository: Path,
) -> None:
    source_path = clean_gate1_repository / "app" / "本地输入.py"
    source_path.write_text("UNTRACKED = True\n", encoding="utf-8")

    result = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=clean_gate1_repository / ".dockerignore",
    )

    assert result["status"] == "DIRTY_BUILD_CONTEXT"
    assert result["details"]["dirty_paths"] == ["app/本地输入.py"]


def test_untracked_test_excluded_from_build_context_keeps_context_ready(
    clean_gate1_repository: Path,
) -> None:
    before = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=clean_gate1_repository / ".dockerignore",
    )
    test_path = clean_gate1_repository / "tests" / "local_probe.py"
    test_path.parent.mkdir()
    test_path.write_text("LOCAL_ONLY = True\n", encoding="utf-8")

    after = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=clean_gate1_repository / ".dockerignore",
    )

    assert after["status"] == "READY"
    assert after["ready"] is True
    assert after["details"]["dirty_paths"] == []
    assert after["binding"] == before["binding"]


def test_nested_python_generated_file_is_excluded_without_changing_fingerprint(
    clean_gate1_repository: Path,
) -> None:
    before = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=clean_gate1_repository / ".dockerignore",
    )
    generated_path = clean_gate1_repository / "app" / "__pycache__" / "generated.pyc"
    generated_path.parent.mkdir()
    generated_path.write_bytes(b"local bytecode")

    after = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=clean_gate1_repository / ".dockerignore",
    )

    assert after["status"] == "READY"
    assert after["ready"] is True
    assert after["binding"] == before["binding"]


def test_nested_pytest_cache_is_excluded_without_changing_fingerprint(
    clean_gate1_repository: Path,
) -> None:
    before = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=clean_gate1_repository / ".dockerignore",
    )
    cache_path = clean_gate1_repository / "app" / ".pytest_cache" / "v" / "cache" / "nodeids"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text("[]\n", encoding="utf-8")

    after = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=clean_gate1_repository / ".dockerignore",
    )

    assert after["status"] == "READY"
    assert after["binding"] == before["binding"]


def test_nested_environment_secret_is_excluded_without_changing_fingerprint(
    clean_gate1_repository: Path,
) -> None:
    before = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=clean_gate1_repository / ".dockerignore",
    )
    secret_path = clean_gate1_repository / "app" / ".env.local"
    secret_path.write_text(
        "GATE1_SECRET=must-not-enter-context\n",
        encoding="utf-8",
    )

    after = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=clean_gate1_repository / ".dockerignore",
    )

    assert after["status"] == "READY"
    assert after["binding"] == before["binding"]
    assert "must-not-enter-context" not in str(after)


def test_committed_environment_secret_entering_context_is_rejected(
    clean_gate1_repository: Path,
) -> None:
    dockerignore_path = clean_gate1_repository / ".dockerignore"
    dockerignore_path.write_text(
        "\n".join(
            line
            for line in dockerignore_path.read_text(encoding="utf-8").splitlines()
            if line != "**/.env*"
        )
        + "\n",
        encoding="utf-8",
    )
    secret_path = clean_gate1_repository / "app" / ".env.production"
    secret_path.write_text(
        "GATE1_SECRET=must-never-be-reported\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={clean_gate1_repository}",
            "-C",
            str(clean_gate1_repository),
            "add",
            ".dockerignore",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={clean_gate1_repository}",
            "-C",
            str(clean_gate1_repository),
            "add",
            "--force",
            "app/.env.production",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={clean_gate1_repository}",
            "-C",
            str(clean_gate1_repository),
            "commit",
            "-m",
            "commit unsafe environment input",
        ],
        check=True,
        capture_output=True,
    )

    result = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=dockerignore_path,
    )

    assert result["status"] == "UNSAFE_BUILD_CONTEXT"
    assert result["ready"] is False
    assert "sensitive_paths_in_context" in result["blockers"]
    assert result["details"]["sensitive_paths_in_context"] == ["app/.env.production"]
    assert "must-never-be-reported" not in str(result)


def test_committed_symlink_entering_build_context_is_rejected(
    clean_gate1_repository: Path,
) -> None:
    link_path = clean_gate1_repository / "app" / "linked-lock"
    link_path.write_text("../uv.lock", encoding="utf-8")
    blob = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={clean_gate1_repository}",
            "-C",
            str(clean_gate1_repository),
            "hash-object",
            "-w",
            "app/linked-lock",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={clean_gate1_repository}",
            "-C",
            str(clean_gate1_repository),
            "update-index",
            "--add",
            "--cacheinfo",
            "120000",
            blob,
            "app/linked-lock",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={clean_gate1_repository}",
            "-C",
            str(clean_gate1_repository),
            "commit",
            "-m",
            "add context symlink",
        ],
        check=True,
        capture_output=True,
    )

    result = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=clean_gate1_repository / ".dockerignore",
    )

    assert result["status"] == "UNSAFE_BUILD_CONTEXT"
    assert result["ready"] is False
    assert "included_symlinks" in result["blockers"]
    assert result["details"]["included_symlink_paths"] == ["app/linked-lock"]


def test_dockerfile_specific_ignore_cannot_override_manifest_bound_root_rules(
    clean_gate1_repository: Path,
) -> None:
    specific_ignore = clean_gate1_repository / "Dockerfile.dockerignore"
    specific_ignore.write_text("*\n", encoding="utf-8")
    subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={clean_gate1_repository}",
            "-C",
            str(clean_gate1_repository),
            "add",
            "Dockerfile.dockerignore",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={clean_gate1_repository}",
            "-C",
            str(clean_gate1_repository),
            "commit",
            "-m",
            "add Dockerfile-specific ignore",
        ],
        check=True,
        capture_output=True,
    )

    result = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=clean_gate1_repository / ".dockerignore",
    )

    assert result["status"] == "UNSAFE_BUILD_CONTEXT"
    assert "dockerfile_specific_ignore" in result["blockers"]
    assert result["details"]["dockerfile_specific_ignore_path"] == ("Dockerfile.dockerignore")


def test_unsupported_dockerignore_pattern_fails_closed(
    clean_gate1_repository: Path,
) -> None:
    dockerignore_path = clean_gate1_repository / ".dockerignore"
    dockerignore_path.write_text(
        dockerignore_path.read_text(encoding="utf-8") + "foo**bar\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={clean_gate1_repository}",
            "-C",
            str(clean_gate1_repository),
            "add",
            ".dockerignore",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={clean_gate1_repository}",
            "-C",
            str(clean_gate1_repository),
            "commit",
            "-m",
            "add unsupported dockerignore pattern",
        ],
        check=True,
        capture_output=True,
    )

    result = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=dockerignore_path,
    )

    assert result["status"] == "UNSAFE_BUILD_CONTEXT"
    assert "unsupported_dockerignore_patterns" in result["blockers"]
    assert result["details"]["unsupported_dockerignore_patterns"] == ["foo**bar"]


def test_utf8_bom_in_dockerignore_preserves_docker_exclusion_semantics(
    clean_gate1_repository: Path,
) -> None:
    dockerignore_path = clean_gate1_repository / ".dockerignore"
    before = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=dockerignore_path,
    )
    dockerignore_path.write_bytes(b"\xef\xbb\xbf" + dockerignore_path.read_bytes())
    subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={clean_gate1_repository}",
            "-C",
            str(clean_gate1_repository),
            "add",
            ".dockerignore",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={clean_gate1_repository}",
            "-C",
            str(clean_gate1_repository),
            "commit",
            "-m",
            "store dockerignore with UTF-8 BOM",
        ],
        check=True,
        capture_output=True,
    )

    after = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=dockerignore_path,
    )

    assert after["status"] == "READY"
    assert after["binding"]["file_count"] == before["binding"]["file_count"]


def test_dockerignore_comment_marker_only_applies_in_first_column(
    clean_gate1_repository: Path,
) -> None:
    dockerignore_path = clean_gate1_repository / ".dockerignore"
    before = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=dockerignore_path,
    )
    dockerignore_path.write_text(
        dockerignore_path.read_text(encoding="utf-8") + " #local-generated.txt\n",
        encoding="utf-8",
    )
    generated_path = clean_gate1_repository / "#local-generated.txt"
    generated_path.write_text("excluded generated content\n", encoding="utf-8")
    subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={clean_gate1_repository}",
            "-C",
            str(clean_gate1_repository),
            "add",
            ".dockerignore",
            "#local-generated.txt",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={clean_gate1_repository}",
            "-C",
            str(clean_gate1_repository),
            "commit",
            "-m",
            "add first-column comment probe",
        ],
        check=True,
        capture_output=True,
    )

    after = audit_gate1_build_context(
        repository=clean_gate1_repository,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=dockerignore_path,
    )

    assert after["status"] == "READY"
    assert after["binding"]["file_count"] == before["binding"]["file_count"]
