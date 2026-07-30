import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

PREPARED_MANIFEST_SCHEMA_VERSION = 2

KEY_EXECUTION_SCRIPT_PATHS = (
    "scripts/experiment_support.py",
    "scripts/gate1_collectors.py",
    "scripts/gate1_database.py",
    "scripts/gate1_evidence.py",
    "scripts/gate1_finalization.py",
    "scripts/gate1_plots.py",
    "scripts/gate1_preflight.py",
    "scripts/gate1_prepared_evidence.py",
    "scripts/run_load_test.py",
    "scripts/worker_scaling_protocol.py",
)
PREPARED_CONFIGURATION_KEYS = frozenset(
    {
        "api_url",
        "api_key_env",
        "database_url_env",
        "workers",
        "cases",
        "warmup_cases",
        "delay_ms",
        "poll_seconds",
        "deadline_seconds",
        "readiness_deadline_seconds",
        "collector_interval_seconds",
        "seed",
        "repetitions",
    }
)

_REQUIRED_DIGEST_PATHS = (
    "protocol.sha256",
    "provenance.compose.sha256",
    "provenance.dockerfile.sha256",
    "provenance.dockerignore.sha256",
    "configuration.sha256",
    "dataset.hashes_sha256",
    "dataset.measurement_sha256",
    "dataset.warmup_sha256",
    "arm_plan.sha256",
)
_REQUIRED_FILE_PATHS = (
    "protocol.path",
    "provenance.compose.path",
    "provenance.dockerfile.path",
    "provenance.dockerignore.path",
    "dataset.hashes_path",
    "dataset.measurement_path",
    "dataset.warmup_path",
    "arm_plan.path",
)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical_json_sha256(value: Mapping[str, Any]) -> str:
    content = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256_bytes(content)


def _manifest_value(manifest: Mapping[str, Any], dotted_path: str) -> Any:
    value: Any = manifest
    for segment in dotted_path.split("."):
        if not isinstance(value, Mapping) or segment not in value:
            raise KeyError(dotted_path)
        value = value[segment]
    return value


def _path_stays_within(root: Path, value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    candidate = Path(value)
    if candidate.is_absolute():
        return False
    try:
        (root / candidate).resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _required_manifest_errors(
    manifest: object,
    *,
    run_directory: Path,
    repository: Path,
) -> list[str]:
    if not isinstance(manifest, Mapping):
        return ["manifest"]
    errors = []
    if manifest.get("schema_version") != PREPARED_MANIFEST_SCHEMA_VERSION:
        errors.append("schema_version")
    if manifest.get("experiment") != "worker_scaling":
        errors.append("experiment")
    if manifest.get("run_id") != run_directory.name:
        errors.append("run_id")
    if manifest.get("status") != "prepared":
        errors.append("status")
    if manifest.get("formal_run_started") is not False:
        errors.append("formal_run_started")
    if (
        _optional_manifest_value(manifest, "adoption_gate.automatic_worker_count_change")
        is not False
    ):
        errors.append("adoption_gate.automatic_worker_count_change")
    if _optional_manifest_value(manifest, "adoption_gate.decision_owner") != "human":
        errors.append("adoption_gate.decision_owner")
    if _optional_manifest_value(manifest, "provenance.execution_scripts.algorithm") != "sha256":
        errors.append("provenance.execution_scripts.algorithm")
    if _optional_manifest_value(manifest, "dataset.algorithm") != "sha256":
        errors.append("dataset.algorithm")
    source_commit = _optional_manifest_value(manifest, "provenance.source_commit")
    if not isinstance(source_commit, str) or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        errors.append("provenance.source_commit")
    for dotted_path in _REQUIRED_FILE_PATHS:
        value = _optional_manifest_value(manifest, dotted_path)
        if not isinstance(value, str) or not value:
            errors.append(dotted_path)
            continue
        allowed_root = repository if dotted_path.startswith("provenance.") else run_directory
        if not _path_stays_within(allowed_root, value):
            errors.append(dotted_path)
    for dotted_path in _REQUIRED_DIGEST_PATHS:
        value = _optional_manifest_value(manifest, dotted_path)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            errors.append(dotted_path)
    configuration = _optional_manifest_value(manifest, "configuration.values")
    if not isinstance(configuration, Mapping) or set(configuration) != PREPARED_CONFIGURATION_KEYS:
        errors.append("configuration.values")
    script_hashes = _optional_manifest_value(
        manifest,
        "provenance.execution_scripts.files",
    )
    if not isinstance(script_hashes, Mapping):
        errors.append("provenance.execution_scripts.files")
    else:
        unexpected_paths = set(script_hashes) - set(KEY_EXECUTION_SCRIPT_PATHS)
        errors.extend(
            f"provenance.execution_scripts.files.{path}" for path in sorted(unexpected_paths)
        )
        for path in KEY_EXECUTION_SCRIPT_PATHS:
            digest = script_hashes.get(path)
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                errors.append(f"provenance.execution_scripts.files.{path}")
            if not _path_stays_within(repository, path):
                errors.append(f"provenance.execution_scripts.files.{path}")
    return errors


def _optional_manifest_value(manifest: Mapping[str, Any], dotted_path: str) -> Any:
    try:
        return _manifest_value(manifest, dotted_path)
    except KeyError:
        return None


def _dockerignore_rules(path: Path) -> list[tuple[bool, str]]:
    rules: list[tuple[bool, str]] = []
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return rules
    for raw_line in content.splitlines():
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
    rules: list[tuple[bool, str]],
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


def _digest_matches(
    *,
    check: str,
    path: str,
    expected_sha256: str,
    observed_sha256: str | None,
    mismatches: list[dict[str, str | None]],
) -> bool:
    matches = observed_sha256 == expected_sha256
    if not matches:
        mismatches.append(
            {
                "check": check,
                "path": path,
                "expected_sha256": expected_sha256,
                "observed_sha256": observed_sha256,
            }
        )
    return matches


def _file_hash_matches(
    *,
    check: str,
    path_label: str,
    path: Path,
    expected_sha256: str,
    mismatches: list[dict[str, str | None]],
) -> bool:
    try:
        observed_sha256 = sha256_file(path)
    except OSError:
        observed_sha256 = None
    return _digest_matches(
        check=check,
        path=path_label,
        expected_sha256=expected_sha256,
        observed_sha256=observed_sha256,
        mismatches=mismatches,
    )


def verify_prepared_evidence(
    *,
    run_directory: Path,
    repository: Path,
    compose_file: Path,
    requested_configuration: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Revalidate a prepared Gate 1 bundle before any environment interaction."""
    repository = repository.resolve()
    try:
        manifest = json.loads((run_directory / "manifest.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        manifest = None
    manifest_errors = _required_manifest_errors(
        manifest,
        run_directory=run_directory,
        repository=repository,
    )
    if manifest_errors:
        observed_schema = manifest.get("schema_version") if isinstance(manifest, Mapping) else None
        return {
            "status": "MANIFEST_INVALID",
            "ready": False,
            "checks": {"manifest_valid": False},
            "blockers": ["manifest_valid"],
            "details": {
                "manifest_errors": manifest_errors,
                "manifest_schema": {
                    "expected": PREPARED_MANIFEST_SCHEMA_VERSION,
                    "observed": observed_schema,
                },
                "hash_mismatches": [],
                "dirty_build_context_paths": [],
            },
        }
    assert isinstance(manifest, Mapping)
    head = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repository}",
            "-C",
            str(repository),
            "rev-parse",
            "HEAD",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    observed_source_commit = head.stdout.strip() or None
    expected_source_commit = str(manifest["provenance"]["source_commit"])
    worktree = subprocess.run(
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
    worktree_rows = [row for row in worktree.stdout.splitlines() if len(row) >= 4]
    git_repository_available = head.returncode == 0 and worktree.returncode == 0
    tracked_dirty_paths = [
        row[3:].replace("\\", "/") for row in worktree_rows if not row.startswith(("?? ", "!! "))
    ]
    build_context_candidates = [
        row[3:].replace("\\", "/") for row in worktree_rows if row.startswith(("?? ", "!! "))
    ]
    measurement_path = run_directory / str(manifest["dataset"]["measurement_path"])
    warmup_path = run_directory / str(manifest["dataset"]["warmup_path"])
    dataset_hashes_path = run_directory / str(manifest["dataset"]["hashes_path"])
    protocol_path = run_directory / str(manifest["protocol"]["path"])
    arm_plan_path = run_directory / str(manifest["arm_plan"]["path"])
    compose_path = repository / str(manifest["provenance"]["compose"]["path"])
    requested_compose_path = (
        compose_file if compose_file.is_absolute() else repository / compose_file
    ).resolve()
    dockerfile_path = repository / str(manifest["provenance"]["dockerfile"]["path"])
    dockerignore_path = repository / str(manifest["provenance"]["dockerignore"]["path"])
    dockerignore_rules = _dockerignore_rules(dockerignore_path)
    dirty_build_context_paths = sorted(
        path
        for path in build_context_candidates
        if _docker_context_includes(path, dockerignore_rules)
    )
    hash_mismatches: list[dict[str, str | None]] = []
    execution_script_hashes_match = True
    for path, expected_sha256 in manifest["provenance"]["execution_scripts"]["files"].items():
        execution_script_hashes_match &= _file_hash_matches(
            check="execution_script_hashes_match",
            path_label=str(path),
            path=repository / str(path),
            expected_sha256=str(expected_sha256),
            mismatches=hash_mismatches,
        )
    configuration_values = manifest["configuration"]["values"]
    checks = {
        "manifest_valid": True,
        "git_repository_available": git_repository_available,
        "source_commit_matches": (
            head.returncode == 0 and observed_source_commit == expected_source_commit
        ),
        "tracked_worktree_clean": worktree.returncode == 0 and not tracked_dirty_paths,
        "docker_build_context_clean": (worktree.returncode == 0 and not dirty_build_context_paths),
        "measurement_hash_matches": _file_hash_matches(
            check="measurement_hash_matches",
            path_label=str(manifest["dataset"]["measurement_path"]),
            path=measurement_path,
            expected_sha256=str(manifest["dataset"]["measurement_sha256"]),
            mismatches=hash_mismatches,
        ),
        "warmup_hash_matches": _file_hash_matches(
            check="warmup_hash_matches",
            path_label=str(manifest["dataset"]["warmup_path"]),
            path=warmup_path,
            expected_sha256=str(manifest["dataset"]["warmup_sha256"]),
            mismatches=hash_mismatches,
        ),
        "dataset_hashes_file_hash_matches": _file_hash_matches(
            check="dataset_hashes_file_hash_matches",
            path_label=str(manifest["dataset"]["hashes_path"]),
            path=dataset_hashes_path,
            expected_sha256=str(manifest["dataset"]["hashes_sha256"]),
            mismatches=hash_mismatches,
        ),
        "protocol_hash_matches": _file_hash_matches(
            check="protocol_hash_matches",
            path_label=str(manifest["protocol"]["path"]),
            path=protocol_path,
            expected_sha256=str(manifest["protocol"]["sha256"]),
            mismatches=hash_mismatches,
        ),
        "arm_plan_hash_matches": _file_hash_matches(
            check="arm_plan_hash_matches",
            path_label=str(manifest["arm_plan"]["path"]),
            path=arm_plan_path,
            expected_sha256=str(manifest["arm_plan"]["sha256"]),
            mismatches=hash_mismatches,
        ),
        "compose_hash_matches": _file_hash_matches(
            check="compose_hash_matches",
            path_label=str(manifest["provenance"]["compose"]["path"]),
            path=compose_path,
            expected_sha256=str(manifest["provenance"]["compose"]["sha256"]),
            mismatches=hash_mismatches,
        ),
        "requested_compose_matches": requested_compose_path == compose_path.resolve(),
        "dockerfile_hash_matches": _file_hash_matches(
            check="dockerfile_hash_matches",
            path_label=str(manifest["provenance"]["dockerfile"]["path"]),
            path=dockerfile_path,
            expected_sha256=str(manifest["provenance"]["dockerfile"]["sha256"]),
            mismatches=hash_mismatches,
        ),
        "dockerignore_hash_matches": _file_hash_matches(
            check="dockerignore_hash_matches",
            path_label=str(manifest["provenance"]["dockerignore"]["path"]),
            path=dockerignore_path,
            expected_sha256=str(manifest["provenance"]["dockerignore"]["sha256"]),
            mismatches=hash_mismatches,
        ),
        "configuration_hash_matches": _digest_matches(
            check="configuration_hash_matches",
            path="configuration.values",
            expected_sha256=str(manifest["configuration"]["sha256"]),
            observed_sha256=canonical_json_sha256(configuration_values),
            mismatches=hash_mismatches,
        ),
        "execution_script_hashes_match": execution_script_hashes_match,
    }
    if requested_configuration is not None:
        checks["requested_configuration_matches"] = _digest_matches(
            check="requested_configuration_matches",
            path="execution_configuration",
            expected_sha256=str(manifest["configuration"]["sha256"]),
            observed_sha256=canonical_json_sha256(requested_configuration),
            mismatches=hash_mismatches,
        )
    blockers = [check for check, passed in checks.items() if not passed]
    if not checks["git_repository_available"]:
        status = "ENVIRONMENT_BLOCKED"
    elif not checks["source_commit_matches"]:
        status = "SOURCE_MISMATCH"
    elif any(
        not checks[check]
        for check in checks
        if check.endswith("_hash_matches")
        or check
        in {
            "execution_script_hashes_match",
            "requested_compose_matches",
            "requested_configuration_matches",
        }
    ):
        status = "HASH_MISMATCH"
    elif not checks["tracked_worktree_clean"] or not checks["docker_build_context_clean"]:
        status = "DIRTY_BUILD_CONTEXT"
    else:
        status = "READY"
    return {
        "status": status,
        "ready": not blockers,
        "checks": checks,
        "blockers": blockers,
        "details": {
            "hash_mismatches": hash_mismatches,
            "expected_source_commit": expected_source_commit,
            "observed_source_commit": observed_source_commit,
            "tracked_dirty_paths": tracked_dirty_paths,
            "dirty_build_context_paths": dirty_build_context_paths,
            "git_head_returncode": head.returncode,
            "git_status_returncode": worktree.returncode,
        },
    }
