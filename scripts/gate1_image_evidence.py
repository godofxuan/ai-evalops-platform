import hashlib
import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from scripts.experiment_support import ExperimentError

APPLICATION_SERVICES = frozenset({"api", "worker", "reaper"})
BUILD_CONTEXT_ALGORITHM = "docker-context-sha256-v1"
COMPOSE_PROJECT = "ai-evalops-platform"
IMAGE_REFERENCE = "ai-evalops-platform:phase9"
IMAGE_REPOSITORY = "ai-evalops-platform"
IMAGE_SOURCE = "https://github.com/godofxuan/ai-evalops-platform"
IMAGE_TAG = "phase9"
PYTHON_VERSION = "3.12.13"


def _dockerignore_rules(path: Path) -> list[tuple[bool, str]]:
    rules: list[tuple[bool, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip().replace("\\", "/")
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        pattern = line[1:] if negated else line
        pattern = pattern.lstrip("/").rstrip("/")
        if pattern and pattern != ".":
            rules.append((negated, pattern))
    return rules


def _docker_context_includes(
    path: str,
    rules: Sequence[tuple[bool, str]],
) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    segments = normalized.split("/")
    excluded = False
    for negated, pattern in rules:
        if "/" not in pattern:
            matched = any(fnmatchcase(segment, pattern) for segment in segments)
        else:
            ancestors = ("/".join(segments[:index]) for index in range(1, len(segments) + 1))
            matched = any(fnmatchcase(ancestor, pattern) for ancestor in ancestors)
        if matched:
            excluded = not negated
    return not excluded


def _unrecorded_build_context_paths(
    *,
    repository: Path,
    dockerignore_path: Path,
) -> list[str]:
    status = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repository}",
            "-C",
            str(repository),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignored=matching",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        raise ExperimentError("unable to inspect the Gate 1 Docker build context")
    rules = _dockerignore_rules(dockerignore_path)
    unrecorded: set[str] = set()
    for row in status.stdout.splitlines():
        if len(row) < 4:
            continue
        path = row[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip('"').replace("\\", "/")
        if _docker_context_includes(path, rules):
            unrecorded.add(path)
    return sorted(unrecorded)


def compute_docker_build_context_binding(
    *,
    repository: Path,
    dockerignore_path: Path,
) -> dict[str, Any]:
    """Hash the regular files and symlink targets entering the Docker context."""
    rules = _dockerignore_rules(dockerignore_path)
    files: list[dict[str, Any]] = []

    for path in sorted(repository.rglob("*")):
        relative = path.relative_to(repository).as_posix()
        if not _docker_context_includes(relative, rules):
            continue
        if path.is_symlink():
            content = path.readlink().as_posix().encode()
            kind = "symlink"
        elif path.is_file():
            content = path.read_bytes()
            kind = "file"
        else:
            continue
        files.append(
            {
                "path": relative,
                "kind": kind,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )

    canonical = json.dumps(
        files,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        "algorithm": BUILD_CONTEXT_ALGORITHM,
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "file_count": len(files),
    }


def _run_checked(
    command: Sequence[str],
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            check=True,
            capture_output=True,
            cwd=cwd,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ExperimentError(f"required executable is unavailable: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise ExperimentError(f"command failed ({' '.join(command)}){suffix}") from exc


def _validated_local_image_inspection(
    *,
    repository: Path,
    expected_labels: Mapping[str, str],
) -> tuple[str, str, str, str]:
    inspection = _run_checked(
        ["docker", "image", "inspect", IMAGE_REFERENCE],
        cwd=repository,
    )
    try:
        payload = json.loads(inspection.stdout)
    except json.JSONDecodeError as exc:
        raise ExperimentError("docker image inspect returned invalid JSON") from exc
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise ExperimentError("docker image inspect did not return exactly one image")

    image = payload[0]
    image_id = image.get("Id")
    if not isinstance(image_id, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise ExperimentError("docker image inspect returned an invalid immutable image ID")

    repository_tags = image.get("RepoTags")
    if not isinstance(repository_tags, list) or IMAGE_REFERENCE not in repository_tags:
        raise ExperimentError(
            f"built image is not tagged with the expected reference: {IMAGE_REFERENCE}"
        )

    config = image.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    if not isinstance(labels, dict):
        raise ExperimentError("built image is missing required OCI/build-input labels")
    for key, expected in expected_labels.items():
        if labels.get(key) != expected:
            raise ExperimentError(
                f"built image label mismatch for {key}: "
                f"expected {expected!r}, observed {labels.get(key)!r}"
            )

    created = image.get("Created")
    if not isinstance(created, str) or not created.strip():
        raise ExperimentError("docker image inspect returned no image creation timestamp")
    operating_system = image.get("Os")
    architecture = image.get("Architecture")
    if not isinstance(operating_system, str) or not operating_system:
        raise ExperimentError("docker image inspect returned no operating system")
    if not isinstance(architecture, str) or not architecture:
        raise ExperimentError("docker image inspect returned no architecture")
    return image_id, created, operating_system, architecture


def build_gate1_image_binding(
    *,
    repository: Path,
    source_commit: str,
    dockerfile_path: Path,
    dockerignore_path: Path,
) -> dict[str, Any]:
    """Build and inspect the immutable local image used by a prepared Gate 1 run."""
    unrecorded_paths = _unrecorded_build_context_paths(
        repository=repository,
        dockerignore_path=dockerignore_path,
    )
    if unrecorded_paths:
        raise ExperimentError(
            "Docker build context contains unrecorded paths: " + ", ".join(unrecorded_paths)
        )

    dockerfile_sha256 = hashlib.sha256(dockerfile_path.read_bytes()).hexdigest()
    build_context = compute_docker_build_context_binding(
        repository=repository,
        dockerignore_path=dockerignore_path,
    )
    build_created = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    labels = {
        "org.opencontainers.image.revision": source_commit,
        "org.opencontainers.image.source": IMAGE_SOURCE,
        "org.opencontainers.image.created": build_created,
        "io.ai-evalops.dockerfile.sha256": dockerfile_sha256,
        "io.ai-evalops.build-context.sha256": build_context["sha256"],
        "io.ai-evalops.python.version": PYTHON_VERSION,
    }

    build_command = [
        "docker",
        "build",
        "--file",
        str(dockerfile_path),
        "--tag",
        IMAGE_REFERENCE,
    ]
    for key, value in labels.items():
        build_command.extend(["--label", f"{key}={value}"])
    build_command.append(str(repository))
    _run_checked(build_command, cwd=repository)
    post_build_context = compute_docker_build_context_binding(
        repository=repository,
        dockerignore_path=dockerignore_path,
    )
    post_build_unrecorded_paths = _unrecorded_build_context_paths(
        repository=repository,
        dockerignore_path=dockerignore_path,
    )
    if post_build_context != build_context or post_build_unrecorded_paths:
        detail = (
            ": " + ", ".join(post_build_unrecorded_paths) if post_build_unrecorded_paths else ""
        )
        raise ExperimentError(f"Docker build context changed during image build{detail}")

    image_id, image_created, operating_system, architecture = _validated_local_image_inspection(
        repository=repository,
        expected_labels=labels,
    )
    runtime = _run_checked(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "python",
            image_id,
            "--version",
        ],
        cwd=repository,
    )
    runtime_text = f"{runtime.stdout}\n{runtime.stderr}".strip()
    runtime_match = re.search(r"\bPython (\d+\.\d+\.\d+)\b", runtime_text)
    if runtime_match is None:
        raise ExperimentError("built image did not report a parseable Python runtime version")
    observed_python = runtime_match.group(1)
    if observed_python != PYTHON_VERSION:
        raise ExperimentError(
            f"built image Python runtime mismatch: expected {PYTHON_VERSION}, "
            f"observed {observed_python}"
        )

    return {
        "identity_kind": "LOCAL_IMAGE_ID",
        "verification": "LOCAL_IMAGE_ID_VERIFIED",
        "repository": IMAGE_REPOSITORY,
        "tag": IMAGE_TAG,
        "reference": IMAGE_REFERENCE,
        "immutable_id": image_id,
        "registry_digest": None,
        "compose_project": COMPOSE_PROJECT,
        "source_commit": source_commit,
        "source": IMAGE_SOURCE,
        "dockerfile_sha256": dockerfile_sha256,
        "build_context": build_context,
        "build": {
            "created": build_created,
            "image_created": image_created,
        },
        "runtime": {
            "python": observed_python,
            "os": operating_system,
            "architecture": architecture,
        },
        "labels": labels,
    }


def gate1_image_binding_errors(
    image: object,
    *,
    expected_source_commit: object,
    expected_dockerfile_sha256: object,
) -> list[str]:
    """Return manifest paths that fail local-image schema or cross-binding checks."""
    prefix = "provenance.image"
    if not isinstance(image, Mapping):
        return [prefix]

    errors: list[str] = []

    def require_equal(field: str, expected: object) -> object:
        value = image.get(field)
        if value != expected:
            errors.append(f"{prefix}.{field}")
        return value

    require_equal("identity_kind", "LOCAL_IMAGE_ID")
    require_equal("verification", "LOCAL_IMAGE_ID_VERIFIED")
    require_equal("repository", IMAGE_REPOSITORY)
    require_equal("tag", IMAGE_TAG)
    require_equal("reference", IMAGE_REFERENCE)
    immutable_id = image.get("immutable_id")
    if (
        not isinstance(immutable_id, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", immutable_id) is None
    ):
        errors.append(f"{prefix}.immutable_id")
    if image.get("registry_digest", object()) is not None:
        errors.append(f"{prefix}.registry_digest")
    require_equal("compose_project", COMPOSE_PROJECT)

    source_commit = image.get("source_commit")
    if (
        not isinstance(source_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
        or source_commit != expected_source_commit
    ):
        errors.append(f"{prefix}.source_commit")
    source = require_equal("source", IMAGE_SOURCE)
    dockerfile_sha256 = image.get("dockerfile_sha256")
    if (
        not isinstance(dockerfile_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", dockerfile_sha256) is None
        or dockerfile_sha256 != expected_dockerfile_sha256
    ):
        errors.append(f"{prefix}.dockerfile_sha256")

    build_context = image.get("build_context")
    if not isinstance(build_context, Mapping):
        errors.append(f"{prefix}.build_context")
        context_sha256 = None
    else:
        if build_context.get("algorithm") != BUILD_CONTEXT_ALGORITHM:
            errors.append(f"{prefix}.build_context.algorithm")
        context_sha256 = build_context.get("sha256")
        if (
            not isinstance(context_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", context_sha256) is None
        ):
            errors.append(f"{prefix}.build_context.sha256")
        file_count = build_context.get("file_count")
        if not isinstance(file_count, int) or isinstance(file_count, bool) or file_count < 1:
            errors.append(f"{prefix}.build_context.file_count")

    build = image.get("build")
    build_created = build.get("created") if isinstance(build, Mapping) else None
    build_timestamp_valid = False
    if isinstance(build_created, str) and build_created.endswith("Z"):
        try:
            datetime.fromisoformat(build_created.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            build_timestamp_valid = True
    if not build_timestamp_valid:
        errors.append(f"{prefix}.build.created")

    runtime = image.get("runtime")
    if not isinstance(runtime, Mapping):
        runtime = {}
    runtime_python = runtime.get("python")
    if runtime_python != PYTHON_VERSION:
        errors.append(f"{prefix}.runtime.python")
    for field in ("os", "architecture"):
        value = runtime.get(field)
        if not isinstance(value, str) or not value:
            errors.append(f"{prefix}.runtime.{field}")

    labels = image.get("labels")
    if not isinstance(labels, Mapping):
        labels = {}
    expected_labels = {
        "org.opencontainers.image.revision": source_commit,
        "org.opencontainers.image.source": source,
        "org.opencontainers.image.created": build_created,
        "io.ai-evalops.dockerfile.sha256": dockerfile_sha256,
        "io.ai-evalops.build-context.sha256": context_sha256,
        "io.ai-evalops.python.version": runtime_python,
    }
    for label, expected in expected_labels.items():
        if labels.get(label) != expected or not isinstance(expected, str):
            errors.append(f"{prefix}.labels.{label}")
    return errors


def _container_label(
    container: Mapping[str, Any],
    name: str,
) -> object:
    labels = container.get("labels")
    return labels.get(name) if isinstance(labels, Mapping) else None


def evaluate_running_image_binding(
    *,
    expected_image: Mapping[str, Any],
    containers: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare running application containers with one immutable image binding."""
    identity_kind_supported = expected_image.get("identity_kind") == "LOCAL_IMAGE_ID"
    expected_image_id = expected_image.get("immutable_id")
    expected_source_commit = expected_image.get("source_commit")
    expected_compose_project = expected_image.get("compose_project")
    expected_dockerfile_sha256 = expected_image.get("dockerfile_sha256")
    expected_build_context = expected_image.get("build_context")
    expected_build_context_sha256 = (
        expected_build_context.get("sha256")
        if isinstance(expected_build_context, Mapping)
        else None
    )
    application_containers = [
        container for container in containers if container.get("service") in APPLICATION_SERVICES
    ]
    observed_services = {str(container.get("service")) for container in application_containers}
    container_image_ids_match = (
        isinstance(expected_image_id, str)
        and observed_services == APPLICATION_SERVICES
        and all(
            container.get("image_id") == expected_image_id for container in application_containers
        )
    )
    revision_labels = [
        _container_label(container, "org.opencontainers.image.revision")
        for container in application_containers
    ]
    image_revision_labels_present = bool(application_containers) and all(
        isinstance(revision, str) and bool(revision) for revision in revision_labels
    )
    image_revision_labels_match = (
        isinstance(expected_source_commit, str)
        and image_revision_labels_present
        and all(revision == expected_source_commit for revision in revision_labels)
    )
    compose_project_matches = (
        isinstance(expected_compose_project, str)
        and bool(application_containers)
        and all(
            _container_label(container, "com.docker.compose.project") == expected_compose_project
            for container in application_containers
        )
    )
    image_build_input_labels_match = (
        isinstance(expected_dockerfile_sha256, str)
        and isinstance(expected_build_context_sha256, str)
        and bool(application_containers)
        and all(
            _container_label(container, "io.ai-evalops.dockerfile.sha256")
            == expected_dockerfile_sha256
            and _container_label(
                container,
                "io.ai-evalops.build-context.sha256",
            )
            == expected_build_context_sha256
            for container in application_containers
        )
    )
    ready = (
        identity_kind_supported
        and container_image_ids_match
        and image_revision_labels_match
        and compose_project_matches
        and image_build_input_labels_match
    )
    if not identity_kind_supported:
        status = "IMAGE_IDENTITY_KIND_UNSUPPORTED"
    elif not container_image_ids_match:
        status = "IMAGE_ID_MISMATCH"
    elif not image_revision_labels_present:
        status = "IMAGE_REVISION_LABEL_MISSING"
    elif not image_revision_labels_match:
        status = "IMAGE_REVISION_MISMATCH"
    elif not compose_project_matches:
        status = "COMPOSE_PROJECT_MISMATCH"
    elif not image_build_input_labels_match:
        status = "IMAGE_BUILD_INPUT_MISMATCH"
    else:
        status = "LOCAL_IMAGE_ID_VERIFIED"
    return {
        "status": status,
        "ready": ready,
        "checks": {
            "identity_kind_supported": identity_kind_supported,
            "container_image_ids_match": container_image_ids_match,
            "image_revision_labels_present": image_revision_labels_present,
            "image_revision_labels_match": image_revision_labels_match,
            "compose_project_matches": compose_project_matches,
            "image_build_input_labels_match": image_build_input_labels_match,
        },
    }
