import json
import subprocess
from pathlib import Path

import pytest

import scripts.gate1_image_evidence as gate1_image_evidence
from scripts.experiment_support import ExperimentError
from scripts.gate1_image_evidence import build_gate1_image_binding, evaluate_running_image_binding


def test_image_build_rejects_untracked_python_entering_build_context(
    clean_gate1_repository: Path,
) -> None:
    untracked_path = clean_gate1_repository / "app" / "untracked_image_input.py"
    untracked_path.write_text("UNTRACKED = True\n", encoding="utf-8")

    with pytest.raises(
        ExperimentError,
        match=r"unrecorded.*app/untracked_image_input\.py",
    ):
        build_gate1_image_binding(
            repository=clean_gate1_repository,
            source_commit="a" * 40,
            dockerfile_path=clean_gate1_repository / "Dockerfile",
            dockerignore_path=clean_gate1_repository / ".dockerignore",
        )


def test_image_build_rejects_tracked_dockerfile_modification_before_docker(
    clean_gate1_repository: Path,
) -> None:
    dockerfile_path = clean_gate1_repository / "Dockerfile"
    dockerfile_path.write_bytes(dockerfile_path.read_bytes() + b"\n# uncommitted image input\n")

    with pytest.raises(
        ExperimentError,
        match=r"unrecorded.*Dockerfile",
    ):
        build_gate1_image_binding(
            repository=clean_gate1_repository,
            source_commit="a" * 40,
            dockerfile_path=dockerfile_path,
            dockerignore_path=clean_gate1_repository / ".dockerignore",
        )


def test_image_build_freezes_local_id_labels_and_runtime(
    clean_gate1_repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_run = subprocess.run
    built_labels: dict[str, str] = {}
    commands: list[list[str]] = []
    image_id = f"sha256:{'a' * 64}"

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[0] == "git":
            return real_run(command, **kwargs)
        commands.append(command)
        if command[:2] == ["docker", "build"]:
            for index, argument in enumerate(command):
                if argument == "--label":
                    key, value = command[index + 1].split("=", 1)
                    built_labels[key] = value
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:3] == ["docker", "image", "inspect"]:
            image = {
                "Id": image_id,
                "RepoTags": ["ai-evalops-platform:phase9"],
                "RepoDigests": [],
                "Created": "2026-07-30T00:00:01Z",
                "Os": "linux",
                "Architecture": "amd64",
                "Config": {
                    "Labels": built_labels,
                },
            }
            return subprocess.CompletedProcess(command, 0, json.dumps([image]), "")
        if command[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(command, 0, "Python 3.12.13\n", "")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(gate1_image_evidence.subprocess, "run", fake_run)

    binding = build_gate1_image_binding(
        repository=clean_gate1_repository,
        source_commit="b" * 40,
        dockerfile_path=clean_gate1_repository / "Dockerfile",
        dockerignore_path=clean_gate1_repository / ".dockerignore",
    )

    assert commands[0][:2] == ["docker", "build"]
    assert built_labels["org.opencontainers.image.revision"] == "b" * 40
    assert (
        built_labels["org.opencontainers.image.source"]
        == "https://github.com/godofxuan/ai-evalops-platform"
    )
    assert built_labels["org.opencontainers.image.created"].endswith("Z")
    assert len(built_labels["io.ai-evalops.dockerfile.sha256"]) == 64
    assert len(built_labels["io.ai-evalops.build-context.sha256"]) == 64
    assert binding["identity_kind"] == "LOCAL_IMAGE_ID"
    assert binding["verification"] == "LOCAL_IMAGE_ID_VERIFIED"
    assert binding["immutable_id"] == image_id
    assert binding["registry_digest"] is None
    assert binding["runtime"] == {
        "python": "3.12.13",
        "os": "linux",
        "architecture": "amd64",
    }


def test_image_build_rejects_context_change_during_docker_build(
    clean_gate1_repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_run = subprocess.run

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "git":
            return real_run(command, **kwargs)
        if command[:2] == ["docker", "build"]:
            (clean_gate1_repository / "app" / "__init__.py").write_text(
                "CHANGED_DURING_BUILD = True\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"unexpected command after context changed: {command}")

    monkeypatch.setattr(gate1_image_evidence.subprocess, "run", fake_run)

    with pytest.raises(
        ExperimentError,
        match=r"build context changed during",
    ):
        build_gate1_image_binding(
            repository=clean_gate1_repository,
            source_commit="b" * 40,
            dockerfile_path=clean_gate1_repository / "Dockerfile",
            dockerignore_path=clean_gate1_repository / ".dockerignore",
        )


def test_running_image_binding_rejects_same_tag_with_different_image_id() -> None:
    expected = {
        "identity_kind": "LOCAL_IMAGE_ID",
        "reference": "ai-evalops-platform:phase9",
        "immutable_id": f"sha256:{'a' * 64}",
    }
    containers = [
        {
            "service": service,
            "image_reference": "ai-evalops-platform:phase9",
            "image_id": f"sha256:{'b' * 64}",
        }
        for service in ("api", "worker", "reaper")
    ]

    result = evaluate_running_image_binding(
        expected_image=expected,
        containers=containers,
    )

    assert result["ready"] is False
    assert result["status"] == "IMAGE_ID_MISMATCH"
    assert result["checks"]["container_image_ids_match"] is False


def test_running_image_binding_rejects_revision_label_mismatch() -> None:
    image_id = f"sha256:{'a' * 64}"
    expected = {
        "identity_kind": "LOCAL_IMAGE_ID",
        "reference": "ai-evalops-platform:phase9",
        "immutable_id": image_id,
        "source_commit": "b" * 40,
    }
    containers = [
        {
            "service": service,
            "image_reference": "ai-evalops-platform:phase9",
            "image_id": image_id,
            "labels": {
                "org.opencontainers.image.revision": "c" * 40,
            },
        }
        for service in ("api", "worker", "reaper")
    ]

    result = evaluate_running_image_binding(
        expected_image=expected,
        containers=containers,
    )

    assert result["ready"] is False
    assert result["status"] == "IMAGE_REVISION_MISMATCH"
    assert result["checks"]["container_image_ids_match"] is True
    assert result["checks"]["image_revision_labels_match"] is False


def test_running_image_binding_rejects_missing_revision_label() -> None:
    image_id = f"sha256:{'a' * 64}"
    expected = {
        "identity_kind": "LOCAL_IMAGE_ID",
        "reference": "ai-evalops-platform:phase9",
        "immutable_id": image_id,
        "source_commit": "b" * 40,
    }
    containers = [
        {
            "service": service,
            "image_reference": "ai-evalops-platform:phase9",
            "image_id": image_id,
            "labels": {},
        }
        for service in ("api", "worker", "reaper")
    ]

    result = evaluate_running_image_binding(
        expected_image=expected,
        containers=containers,
    )

    assert result["ready"] is False
    assert result["status"] == "IMAGE_REVISION_LABEL_MISSING"
    assert result["checks"]["image_revision_labels_present"] is False
    assert result["checks"]["image_revision_labels_match"] is False


def test_running_image_binding_rejects_container_from_another_compose_project() -> None:
    image_id = f"sha256:{'a' * 64}"
    source_commit = "b" * 40
    expected = {
        "identity_kind": "LOCAL_IMAGE_ID",
        "reference": "ai-evalops-platform:phase9",
        "immutable_id": image_id,
        "source_commit": source_commit,
        "compose_project": "ai-evalops-platform",
    }
    containers = [
        {
            "service": service,
            "image_reference": "ai-evalops-platform:phase9",
            "image_id": image_id,
            "labels": {
                "org.opencontainers.image.revision": source_commit,
                "com.docker.compose.project": "unrelated-project",
            },
        }
        for service in ("api", "worker", "reaper")
    ]

    result = evaluate_running_image_binding(
        expected_image=expected,
        containers=containers,
    )

    assert result["ready"] is False
    assert result["status"] == "COMPOSE_PROJECT_MISMATCH"
    assert result["checks"]["container_image_ids_match"] is True
    assert result["checks"]["image_revision_labels_match"] is True
    assert result["checks"]["compose_project_matches"] is False


def test_running_image_binding_rejects_old_image_after_dockerfile_change() -> None:
    image_id = f"sha256:{'a' * 64}"
    source_commit = "b" * 40
    context_sha256 = "c" * 64
    expected = {
        "identity_kind": "LOCAL_IMAGE_ID",
        "reference": "ai-evalops-platform:phase9",
        "immutable_id": image_id,
        "source_commit": source_commit,
        "compose_project": "ai-evalops-platform",
        "dockerfile_sha256": "d" * 64,
        "build_context": {
            "sha256": context_sha256,
        },
    }
    containers = [
        {
            "service": service,
            "image_reference": "ai-evalops-platform:phase9",
            "image_id": image_id,
            "labels": {
                "org.opencontainers.image.revision": source_commit,
                "com.docker.compose.project": "ai-evalops-platform",
                "io.ai-evalops.dockerfile.sha256": "e" * 64,
                "io.ai-evalops.build-context.sha256": context_sha256,
            },
        }
        for service in ("api", "worker", "reaper")
    ]

    result = evaluate_running_image_binding(
        expected_image=expected,
        containers=containers,
    )

    assert result["ready"] is False
    assert result["status"] == "IMAGE_BUILD_INPUT_MISMATCH"
    assert result["checks"]["image_build_input_labels_match"] is False


def test_running_image_binding_reports_verified_local_image_id() -> None:
    image_id = f"sha256:{'a' * 64}"
    source_commit = "b" * 40
    dockerfile_sha256 = "c" * 64
    context_sha256 = "d" * 64
    expected = {
        "identity_kind": "LOCAL_IMAGE_ID",
        "reference": "ai-evalops-platform:phase9",
        "immutable_id": image_id,
        "source_commit": source_commit,
        "compose_project": "ai-evalops-platform",
        "dockerfile_sha256": dockerfile_sha256,
        "build_context": {
            "sha256": context_sha256,
        },
    }
    containers = [
        {
            "service": service,
            "image_reference": "ai-evalops-platform:phase9",
            "image_id": image_id,
            "labels": {
                "org.opencontainers.image.revision": source_commit,
                "com.docker.compose.project": "ai-evalops-platform",
                "io.ai-evalops.dockerfile.sha256": dockerfile_sha256,
                "io.ai-evalops.build-context.sha256": context_sha256,
            },
        }
        for service in ("api", "worker", "reaper")
    ]

    result = evaluate_running_image_binding(
        expected_image=expected,
        containers=containers,
    )

    assert result["ready"] is True
    assert result["status"] == "LOCAL_IMAGE_ID_VERIFIED"
    assert all(result["checks"].values())
    assert "REGISTRY_DIGEST_VERIFIED" not in str(result)
