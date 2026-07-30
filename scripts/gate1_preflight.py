import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts.gate1_image_evidence import (
    APPLICATION_SERVICES,
    evaluate_running_image_binding,
)

REQUIRED_PREFLIGHT_CHECKS = (
    "source_commit_matches",
    "tracked_worktree_clean",
    "docker_cli_available",
    "compose_config_valid",
    "required_services_healthy",
    "disk_space_sufficient",
    "api_key_present",
    "database_url_present",
    "quality_gate_confirmed",
    "adoption_gate_confirmed",
    "identity_kind_supported",
    "container_image_ids_match",
    "image_revision_labels_present",
    "image_revision_labels_match",
    "compose_project_matches",
    "image_build_input_labels_match",
)

IMAGE_CHECK_STATUSES = (
    ("identity_kind_supported", "IMAGE_IDENTITY_KIND_UNSUPPORTED"),
    ("container_image_ids_match", "IMAGE_ID_MISMATCH"),
    ("image_revision_labels_present", "IMAGE_REVISION_LABEL_MISSING"),
    ("image_revision_labels_match", "IMAGE_REVISION_MISMATCH"),
    ("compose_project_matches", "COMPOSE_PROJECT_MISMATCH"),
    ("image_build_input_labels_match", "IMAGE_BUILD_INPUT_MISMATCH"),
)


def evaluate_preflight(observations: Mapping[str, bool]) -> dict[str, Any]:
    """Evaluate sanitized preflight facts without receiving credential values."""
    sanitized = {check: observations.get(check, False) for check in REQUIRED_PREFLIGHT_CHECKS}
    blockers = [check for check, passed in sanitized.items() if not passed]
    if not sanitized["source_commit_matches"]:
        status = "SOURCE_MISMATCH"
    elif not sanitized["tracked_worktree_clean"]:
        status = "DIRTY_BUILD_CONTEXT"
    elif not all(
        sanitized[check]
        for check in (
            "docker_cli_available",
            "compose_config_valid",
            "required_services_healthy",
        )
    ):
        status = "ENVIRONMENT_BLOCKED"
    elif image_failure := next(
        (image_status for check, image_status in IMAGE_CHECK_STATUSES if not sanitized[check]),
        None,
    ):
        status = image_failure
    elif blockers:
        status = "ENVIRONMENT_BLOCKED"
    else:
        status = "READY"
    return {
        "status": status,
        "ready": not blockers,
        "checks": sanitized,
        "blockers": blockers,
    }


def required_services_healthy(services: Sequence[Mapping[str, str]]) -> bool:
    by_service: dict[str, list[Mapping[str, str]]] = {}
    for service in services:
        by_service.setdefault(service.get("Service", ""), []).append(service)
    for service_name in ("postgres", "redis", "api"):
        instances = by_service.get(service_name, [])
        if not instances or any(
            instance.get("State") != "running" or instance.get("Health") != "healthy"
            for instance in instances
        ):
            return False
    reapers = by_service.get("reaper", [])
    workers = by_service.get("worker", [])
    return (
        bool(reapers)
        and all(instance.get("State") == "running" for instance in reapers)
        and bool(workers)
        and all(instance.get("State") == "running" for instance in workers)
    )


def _compose_services(stdout: str) -> list[dict[str, str]]:
    stripped = stdout.strip()
    if not stripped:
        return []
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in stripped.splitlines()]
    else:
        rows = parsed if isinstance(parsed, list) else [parsed]
    return [
        {str(key): str(value) for key, value in row.items()}
        for row in rows
        if isinstance(row, dict)
    ]


def collect_compose_service_rows(*, compose_file: Path) -> list[dict[str, str]]:
    ps = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "ps",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return _compose_services(ps.stdout)


def collect_running_container_image_facts(
    *,
    service_rows: Sequence[Mapping[str, str]],
) -> list[dict[str, Any]]:
    """Inspect the exact application containers returned by Docker Compose."""
    containers: list[dict[str, Any]] = []
    for row in service_rows:
        service = row.get("Service", "")
        if service not in APPLICATION_SERVICES:
            continue
        container_id = row.get("ID", "")
        if not container_id:
            containers.append({"service": service})
            continue
        inspected = subprocess.run(
            ["docker", "inspect", container_id],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(inspected.stdout)
        if (
            not isinstance(payload, list)
            or len(payload) != 1
            or not isinstance(payload[0], Mapping)
        ):
            raise ValueError(f"docker inspect returned no unique container for {container_id}")
        container = payload[0]
        config = container.get("Config")
        labels = config.get("Labels") if isinstance(config, Mapping) else None
        image_reference = config.get("Image") if isinstance(config, Mapping) else None
        containers.append(
            {
                "service": service,
                "container_id": container_id,
                "image_reference": image_reference,
                "image_id": container.get("Image"),
                "labels": dict(labels) if isinstance(labels, Mapping) else {},
            }
        )
    return containers


def collect_preflight(
    *,
    expected_source_commit: str,
    expected_image: Mapping[str, Any],
    compose_file: Path,
    evidence_directory: Path,
    api_key_env: str,
    database_url_env: str,
    quality_gate_confirmed: bool,
    adoption_gate_confirmed: bool,
) -> dict[str, Any]:
    """Collect local preflight facts without returning credential values."""
    repository = Path.cwd()
    git_prefix = ["git", "-c", f"safe.directory={repository}"]
    head = subprocess.run(
        [*git_prefix, "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    status = subprocess.run(
        [*git_prefix, "status", "--porcelain", "--untracked-files=no"],
        check=False,
        capture_output=True,
        text=True,
    )
    docker_available = shutil.which("docker") is not None
    compose_config_valid = False
    service_rows: list[dict[str, str]] = []
    compose_version: str | None = None
    docker_version: str | None = None
    rendered_compose_sha256: str | None = None
    running_containers: list[dict[str, Any]] = []
    if docker_available:
        docker = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            check=False,
            capture_output=True,
            text=True,
        )
        docker_version = docker.stdout.strip() or None
        version = subprocess.run(
            ["docker", "compose", "version", "--short"],
            check=False,
            capture_output=True,
            text=True,
        )
        compose_version = version.stdout.strip() or None
        config = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "config"],
            check=False,
            capture_output=True,
            text=True,
        )
        compose_config_valid = version.returncode == 0 and config.returncode == 0
        if config.returncode == 0:
            rendered_compose_sha256 = hashlib.sha256(config.stdout.encode("utf-8")).hexdigest()
        if compose_config_valid:
            try:
                service_rows = collect_compose_service_rows(compose_file=compose_file)
                running_containers = collect_running_container_image_facts(
                    service_rows=service_rows,
                )
            except (
                json.JSONDecodeError,
                OSError,
                subprocess.SubprocessError,
                TypeError,
                ValueError,
            ):
                service_rows = []
                running_containers = []
    image_verification = evaluate_running_image_binding(
        expected_image=expected_image,
        containers=running_containers,
    )
    observations = {
        "source_commit_matches": (
            head.returncode == 0 and head.stdout.strip() == expected_source_commit
        ),
        "tracked_worktree_clean": status.returncode == 0 and not status.stdout.strip(),
        "docker_cli_available": docker_available,
        "compose_config_valid": compose_config_valid,
        "required_services_healthy": required_services_healthy(service_rows),
        "disk_space_sufficient": shutil.disk_usage(evidence_directory).free >= 20 * 1024**3,
        "api_key_present": bool(os.getenv(api_key_env)),
        "database_url_present": bool(os.getenv(database_url_env)),
        "quality_gate_confirmed": quality_gate_confirmed,
        "adoption_gate_confirmed": adoption_gate_confirmed,
        **image_verification["checks"],
    }
    return {
        **evaluate_preflight(observations),
        "runtime": {
            "observed_source_commit": head.stdout.strip() or None,
            "operating_system": platform.platform(),
            "python": sys.version.split()[0],
            "logical_cpu_count": os.cpu_count(),
            "docker_version": docker_version,
            "compose_version": compose_version,
            "rendered_compose_sha256": rendered_compose_sha256,
            "image_ids": sorted(
                {
                    str(container["image_id"])
                    for container in running_containers
                    if isinstance(container.get("image_id"), str)
                }
            ),
            "image_verification": {
                "status": image_verification["status"],
                "identity_kind": expected_image.get("identity_kind"),
                "reference": expected_image.get("reference"),
                "expected_immutable_id": expected_image.get("immutable_id"),
                "containers": [
                    {
                        "service": container.get("service"),
                        "container_id": container.get("container_id"),
                        "image_reference": container.get("image_reference"),
                        "image_id": container.get("image_id"),
                        "revision": (
                            container.get("labels", {}).get("org.opencontainers.image.revision")
                            if isinstance(container.get("labels"), Mapping)
                            else None
                        ),
                        "compose_project": (
                            container.get("labels", {}).get("com.docker.compose.project")
                            if isinstance(container.get("labels"), Mapping)
                            else None
                        ),
                    }
                    for container in running_containers
                ],
            },
            "service_count": len(service_rows),
            "disk_free_bytes": shutil.disk_usage(evidence_directory).free,
        },
    }
