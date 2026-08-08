import csv
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

RELEASE_BUNDLE_SCHEMA_VERSION = 1
CURRENT_RELEASE_SCOPE = "current_release_capacity"
HISTORICAL_SCOPE = "historical_baseline"
_SOURCE_PATTERN = re.compile(r"[0-9a-f]{40}")
_REQUIRED_COUNT_FIELDS = (
    "submitted_count",
    "unique_job_count",
    "terminal_count",
    "lost_count",
    "duplicate_durable_result_count",
    "stale_success_accepted_count",
    "stale_failure_accepted_count",
    "illegal_state_transition_count",
    "orphan_nonterminal_count",
    "attempt_sequence_mismatch_count",
)


def _read_manifest(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, Mapping) else None


def _payload_files(bundle_directory: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    try:
        paths = list(bundle_directory.rglob("*"))
    except OSError:
        return files
    for path in paths:
        if path.is_symlink() or (path.is_file() and path.name != "manifest.json"):
            files[path.relative_to(bundle_directory).as_posix()] = path
    return files


def _manifest_blockers(
    bundle_directory: Path,
    manifest: Mapping[str, Any] | None,
) -> tuple[list[str], dict[str, Path]]:
    blockers: list[str] = []
    payload_files = _payload_files(bundle_directory)
    if manifest is None:
        return ["manifest_invalid"], payload_files
    if (
        manifest.get("schema_version") != RELEASE_BUNDLE_SCHEMA_VERSION
        or manifest.get("status") != "complete"
    ):
        blockers.append("manifest_invalid")
    declared = manifest.get("files")
    if not isinstance(declared, Mapping):
        blockers.append("manifest_invalid")
        return blockers, payload_files
    if not all(isinstance(path, str) for path in declared):
        blockers.append("manifest_invalid")
        return blockers, payload_files
    if set(declared) != set(payload_files):
        blockers.append("manifest_file_set_mismatch")
    for relative_path in set(declared) & set(payload_files):
        metadata = declared[relative_path]
        if not isinstance(metadata, Mapping):
            blockers.append("manifest_invalid")
            continue
        expected_hash = metadata.get("sha256")
        expected_size = metadata.get("size_bytes")
        path = payload_files[relative_path]
        try:
            content = path.read_bytes()
        except OSError:
            blockers.append("manifest_hash_mismatch")
            continue
        if (
            not isinstance(expected_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
            or type(expected_size) is not int
            or expected_size < 0
        ):
            blockers.append("manifest_invalid")
            continue
        if len(content) != expected_size or hashlib.sha256(content).hexdigest() != expected_hash:
            blockers.append("manifest_hash_mismatch")
    return blockers, payload_files


def _read_arm_rows(path: Path) -> tuple[list[dict[str, str]], str | None]:
    try:
        if path.stat().st_size == 0:
            return [], "arms_csv_empty"
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                return [], "arms_csv_empty"
            rows = list(reader)
    except (csv.Error, OSError, UnicodeError):
        return [], "arms_csv_invalid"
    if not rows:
        return [], "arms_csv_empty"
    required_fields = {
        "arm_id",
        "source_commit",
        "distribution",
        "fair_first_secondary_tenant_position",
        "legacy_fifo_first_secondary_tenant_position",
        *_REQUIRED_COUNT_FIELDS,
    }
    if not required_fields.issubset(reader.fieldnames):
        return rows, "arms_csv_invalid"
    return rows, None


def _integer(row: Mapping[str, str], field: str) -> int | None:
    try:
        value = int(row[field])
    except (KeyError, TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _explain_blocker(payload_files: Mapping[str, Path]) -> str | None:
    explain_paths = [
        path
        for relative_path, path in payload_files.items()
        if relative_path.startswith("explain/") and relative_path.endswith(".json")
    ]
    if not explain_paths:
        return "postgres_explain_missing"
    for path in explain_paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return "postgres_explain_invalid"
        if (
            not isinstance(value, Mapping)
            or value.get("format") != "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)"
            or not isinstance(value.get("plan"), list)
            or not value["plan"]
            or isinstance(value.get("planning_time_ms"), bool)
            or not isinstance(value.get("planning_time_ms"), int | float)
            or isinstance(value.get("execution_time_ms"), bool)
            or not isinstance(value.get("execution_time_ms"), int | float)
        ):
            return "postgres_explain_invalid"
    return None


def _explain_coverage_blocker(
    payload_files: Mapping[str, Path],
    *,
    expected_arm_ids: Sequence[str],
    expected_repetitions: int,
) -> str | None:
    if expected_repetitions <= 0:
        return "expected_explain_contract_invalid"
    expected = {
        (arm_id, selector, repetition)
        for arm_id in expected_arm_ids
        for selector in ("fair", "legacy_fifo")
        for repetition in range(1, expected_repetitions + 1)
    }
    observed: list[tuple[str, str, int]] = []
    for relative_path, path in payload_files.items():
        if not relative_path.startswith("explain/") or not relative_path.endswith(".json"):
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(value, Mapping):
            arm_id = value.get("arm_id")
            selector = value.get("selector")
            repetition = value.get("repetition")
            if isinstance(arm_id, str) and isinstance(selector, str) and type(repetition) is int:
                observed.append((arm_id, selector, repetition))
    return (
        None
        if len(observed) == len(expected) and set(observed) == expected
        else "postgres_explain_coverage_mismatch"
    )


def assess_release_bundle(
    bundle_directory: Path,
    *,
    expected_source_commit: str,
    expected_arm_ids: Sequence[str],
    expected_explain_repetitions: int | None = None,
) -> dict[str, Any]:
    """Assess one immutable RC bundle without weakening missing or failed evidence."""
    bundle_directory = bundle_directory.resolve()
    manifest = _read_manifest(bundle_directory / "manifest.json")
    blockers, payload_files = _manifest_blockers(bundle_directory, manifest)
    missing_arm_ids: list[str] = []
    duplicate_arm_ids: list[str] = []
    unexpected_arm_ids: list[str] = []
    claim_scope = manifest.get("claim_scope") if manifest is not None else None
    source_commit = manifest.get("source_commit") if manifest is not None else None

    if not isinstance(source_commit, str) or _SOURCE_PATTERN.fullmatch(source_commit) is None:
        blockers.append("invalid_source_commit")
    if claim_scope not in {CURRENT_RELEASE_SCOPE, HISTORICAL_SCOPE}:
        blockers.append("claim_scope_invalid")
    elif claim_scope == CURRENT_RELEASE_SCOPE and source_commit != expected_source_commit:
        blockers.append("historical_source_misclassified")

    expected_counts = Counter(expected_arm_ids)
    if not expected_counts or any(count != 1 for count in expected_counts.values()):
        blockers.append("expected_arm_contract_invalid")

    rows, csv_blocker = _read_arm_rows(bundle_directory / "arms.csv")
    if csv_blocker is not None:
        blockers.append(csv_blocker)
    else:
        arm_counts = Counter(row.get("arm_id", "") for row in rows)
        duplicate_arm_ids = sorted(arm_id for arm_id, count in arm_counts.items() if count > 1)
        if duplicate_arm_ids:
            blockers.append("duplicate_arm")
        missing_arm_ids = sorted(set(expected_counts) - set(arm_counts))
        unexpected_arm_ids = sorted(set(arm_counts) - set(expected_counts))
        if missing_arm_ids:
            blockers.append("missing_arm")
        if unexpected_arm_ids:
            blockers.append("unexpected_arm")
        for row in rows:
            row_source = row.get("source_commit")
            if not isinstance(row_source, str) or _SOURCE_PATTERN.fullmatch(row_source) is None:
                blockers.append("invalid_source_commit")
            elif row_source != source_commit:
                blockers.append("row_source_mismatch")
            counts = {field: _integer(row, field) for field in _REQUIRED_COUNT_FIELDS}
            if any(value is None for value in counts.values()):
                blockers.append("arms_csv_invalid")
                continue
            if counts["submitted_count"] != counts["unique_job_count"]:
                blockers.append("submitted_unique_mismatch")
            if counts["unique_job_count"] != counts["terminal_count"]:
                blockers.append("unique_terminal_mismatch")
            if counts["lost_count"] != 0:
                blockers.append("lost_jobs")
            if counts["duplicate_durable_result_count"] != 0:
                blockers.append("duplicate_durable_results")
            if counts["stale_success_accepted_count"] != 0:
                blockers.append("stale_success_accepted")
            if counts["stale_failure_accepted_count"] != 0:
                blockers.append("stale_failure_accepted")
            if counts["illegal_state_transition_count"] != 0:
                blockers.append("illegal_state_transition")
            if counts["orphan_nonterminal_count"] != 0:
                blockers.append("orphan_nonterminal_jobs")
            if counts["attempt_sequence_mismatch_count"] != 0:
                blockers.append("attempt_sequence_mismatch")
            if row.get("distribution") == "skew_20_to_1":
                fair_position = _integer(row, "fair_first_secondary_tenant_position")
                legacy_position = _integer(
                    row,
                    "legacy_fifo_first_secondary_tenant_position",
                )
                if fair_position is None or legacy_position is None:
                    blockers.append("arms_csv_invalid")
                else:
                    if fair_position > 2:
                        blockers.append("skew_fairness_regression")
                    if legacy_position <= 2:
                        blockers.append("legacy_fifo_baseline_invalid")

    explain_blocker = _explain_blocker(payload_files)
    if explain_blocker is not None:
        blockers.append(explain_blocker)
    if expected_explain_repetitions is not None:
        coverage_blocker = _explain_coverage_blocker(
            payload_files,
            expected_arm_ids=tuple(expected_counts),
            expected_repetitions=expected_explain_repetitions,
        )
        if coverage_blocker is not None:
            blockers.append(coverage_blocker)
    unique_blockers = list(dict.fromkeys(blockers))
    if not unique_blockers:
        status = "VERIFIED"
    elif unique_blockers == ["postgres_explain_missing"]:
        status = "UNKNOWN"
    else:
        status = "FAILED"
    return {
        "schema_version": RELEASE_BUNDLE_SCHEMA_VERSION,
        "status": status,
        "source_commit": source_commit,
        "expected_source_commit": expected_source_commit,
        "claim_scope": claim_scope,
        "expected_arm_count": len(expected_counts),
        "observed_arm_count": len(rows),
        "missing_arm_ids": missing_arm_ids,
        "duplicate_arm_ids": duplicate_arm_ids,
        "unexpected_arm_ids": unexpected_arm_ids,
        "expected_explain_repetitions": expected_explain_repetitions,
        "blockers": unique_blockers,
    }
