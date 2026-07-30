import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.gate1_preflight as gate1_preflight
from scripts.gate1_preflight import (
    collect_preflight,
    evaluate_preflight,
    required_services_healthy,
)


def test_preflight_reports_every_blocker_without_secret_values() -> None:
    result = evaluate_preflight(
        {
            "source_commit_matches": True,
            "tracked_worktree_clean": True,
            "docker_cli_available": False,
            "compose_config_valid": False,
            "required_services_healthy": False,
            "disk_space_sufficient": True,
            "api_key_present": True,
            "database_url_present": False,
            "quality_gate_confirmed": True,
            "adoption_gate_confirmed": False,
            "identity_kind_supported": True,
            "container_image_ids_match": True,
            "image_revision_labels_present": True,
            "image_revision_labels_match": True,
            "compose_project_matches": True,
            "image_build_input_labels_match": True,
        }
    )

    assert result["ready"] is False
    assert result["status"] == "ENVIRONMENT_BLOCKED"
    assert result["blockers"] == [
        "docker_cli_available",
        "compose_config_valid",
        "required_services_healthy",
        "database_url_present",
        "adoption_gate_confirmed",
    ]
    assert "secret" not in str(result).lower()


def test_compose_service_health_requires_core_health_and_running_workers() -> None:
    services = [
        {"Service": "postgres", "State": "running", "Health": "healthy"},
        {"Service": "redis", "State": "running", "Health": "healthy"},
        {"Service": "api", "State": "running", "Health": "healthy"},
        {"Service": "reaper", "State": "running", "Health": ""},
        {"Service": "worker", "State": "running", "Health": ""},
        {"Service": "worker", "State": "running", "Health": ""},
    ]

    assert required_services_healthy(services) is True
    services[2]["Health"] = "starting"
    assert required_services_healthy(services) is False


def test_running_image_facts_inspect_exact_compose_application_containers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_rows = [
        {"Service": "postgres", "ID": "postgres-id"},
        {"Service": "api", "ID": "api-id"},
        {"Service": "worker", "ID": "worker-id"},
        {"Service": "reaper", "ID": "reaper-id"},
    ]
    inspected_ids: list[str] = []

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        assert command[:2] == ["docker", "inspect"]
        container_id = command[2]
        inspected_ids.append(container_id)
        payload = [
            {
                "Image": f"sha256:{container_id[0] * 64}",
                "Config": {
                    "Image": "ai-evalops-platform:phase9",
                    "Labels": {
                        "org.opencontainers.image.revision": "b" * 40,
                        "com.docker.compose.project": "ai-evalops-platform",
                    },
                },
            }
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            gate1_preflight.json.dumps(payload),
            "",
        )

    monkeypatch.setattr(gate1_preflight.subprocess, "run", fake_run)

    facts = gate1_preflight.collect_running_container_image_facts(
        service_rows=service_rows,
    )

    assert inspected_ids == ["api-id", "worker-id", "reaper-id"]
    assert [fact["service"] for fact in facts] == ["api", "worker", "reaper"]
    assert all(fact["image_reference"] == "ai-evalops-platform:phase9" for fact in facts)
    assert all(
        fact["labels"]["com.docker.compose.project"] == "ai-evalops-platform" for fact in facts
    )


def test_preflight_keeps_source_and_worktree_failures_distinct_from_environment() -> None:
    otherwise_ready = {
        "source_commit_matches": True,
        "tracked_worktree_clean": True,
        "docker_cli_available": True,
        "compose_config_valid": True,
        "required_services_healthy": True,
        "disk_space_sufficient": True,
        "api_key_present": True,
        "database_url_present": True,
        "quality_gate_confirmed": True,
        "adoption_gate_confirmed": True,
        "identity_kind_supported": True,
        "container_image_ids_match": True,
        "image_revision_labels_present": True,
        "image_revision_labels_match": True,
        "compose_project_matches": True,
        "image_build_input_labels_match": True,
    }

    source_mismatch = evaluate_preflight({**otherwise_ready, "source_commit_matches": False})
    dirty_worktree = evaluate_preflight({**otherwise_ready, "tracked_worktree_clean": False})

    assert source_mismatch["status"] == "SOURCE_MISMATCH"
    assert dirty_worktree["status"] == "DIRTY_BUILD_CONTEXT"


def test_collected_preflight_rejects_running_container_image_id_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_commit = "b" * 40
    expected_image_id = f"sha256:{'a' * 64}"
    expected_image = {
        "identity_kind": "LOCAL_IMAGE_ID",
        "immutable_id": expected_image_id,
        "source_commit": source_commit,
        "compose_project": "ai-evalops-platform",
        "dockerfile_sha256": "c" * 64,
        "build_context": {"sha256": "d" * 64},
    }
    service_rows = [
        {"Service": "postgres", "State": "running", "Health": "healthy"},
        {"Service": "redis", "State": "running", "Health": "healthy"},
        {"Service": "api", "State": "running", "Health": "healthy"},
        {"Service": "worker", "State": "running", "Health": ""},
        {"Service": "reaper", "State": "running", "Health": ""},
    ]
    running_containers = [
        {
            "service": service,
            "image_id": f"sha256:{'e' * 64}",
            "labels": {
                "org.opencontainers.image.revision": source_commit,
                "com.docker.compose.project": "ai-evalops-platform",
                "io.ai-evalops.dockerfile.sha256": "c" * 64,
                "io.ai-evalops.build-context.sha256": "d" * 64,
            },
        }
        for service in ("api", "worker", "reaper")
    ]

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        if "rev-parse" in command:
            return subprocess.CompletedProcess(command, 0, f"{source_commit}\n", "")
        if "status" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(command, 0, "28.0.0\n", "")
        if command[:3] == ["docker", "compose", "version"]:
            return subprocess.CompletedProcess(command, 0, "2.39.0\n", "")
        if "config" in command:
            return subprocess.CompletedProcess(command, 0, "services: {}\n", "")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(gate1_preflight.subprocess, "run", fake_run)
    monkeypatch.setattr(gate1_preflight.shutil, "which", lambda _: "docker.exe")
    monkeypatch.setattr(
        gate1_preflight.platform,
        "platform",
        lambda: "test-platform",
    )
    monkeypatch.setattr(
        gate1_preflight.shutil,
        "disk_usage",
        lambda _: SimpleNamespace(free=100 * 1024**3),
    )
    monkeypatch.setattr(
        gate1_preflight,
        "collect_compose_service_rows",
        lambda **_: service_rows,
    )
    monkeypatch.setattr(
        gate1_preflight,
        "collect_running_container_image_facts",
        lambda **_: running_containers,
        raising=False,
    )
    monkeypatch.setenv("GATE1_TEST_API_KEY", "present")
    monkeypatch.setenv("GATE1_TEST_DATABASE_URL", "present")

    result = collect_preflight(
        expected_source_commit=source_commit,
        expected_image=expected_image,
        compose_file=tmp_path / "compose.yaml",
        evidence_directory=tmp_path,
        api_key_env="GATE1_TEST_API_KEY",
        database_url_env="GATE1_TEST_DATABASE_URL",
        quality_gate_confirmed=True,
        adoption_gate_confirmed=True,
    )

    assert result["ready"] is False
    assert result["status"] == "IMAGE_ID_MISMATCH"
    assert result["checks"]["container_image_ids_match"] is False
    assert result["runtime"]["image_verification"]["status"] == "IMAGE_ID_MISMATCH"
