import csv
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts.experiment_support import ExperimentError, write_report
from scripts.gate1_evidence import (
    GATE1_RESULT_SCHEMA_VERSION,
    aggregate_arm_summaries,
)
from scripts.gate1_prepared_evidence import sha256_file

GATE1_FINAL_BUNDLE_SCHEMA_VERSION = 1
GATE1_FINAL_DIRECTORY_NAME = "final"
GATE1_FINALIZATION_LOCK_NAME = ".gate1-finalize.lock"


def _arm_ids(summary_records: Sequence[dict[str, Any]]) -> list[str]:
    arm_ids: list[str] = []
    for record in summary_records:
        arm = record.get("arm")
        arm_id = arm.get("arm_id") if isinstance(arm, Mapping) else None
        if (
            not isinstance(arm_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", arm_id) is None
        ):
            raise ExperimentError("Gate 1 finalization received an invalid arm_id")
        arm_ids.append(arm_id)
    if not arm_ids:
        raise ExperimentError("Gate 1 finalization requires at least one arm")
    if len(set(arm_ids)) != len(arm_ids):
        raise ExperimentError("Gate 1 finalization received duplicate arm_ids")
    return arm_ids


def _load_json_mapping(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise ExperimentError(f"invalid Gate 1 {label}: {path}") from error
    if not isinstance(value, Mapping):
        raise ExperimentError(f"invalid Gate 1 {label}: {path}")
    return value


def _payload_files(bundle_directory: Path) -> dict[str, Path]:
    try:
        paths = list(bundle_directory.rglob("*"))
    except OSError as error:
        raise ExperimentError("unable to enumerate Gate 1 final bundle files") from error
    symlinks = [
        path.relative_to(bundle_directory).as_posix() for path in paths if path.is_symlink()
    ]
    if symlinks:
        raise ExperimentError(
            f"Gate 1 final bundle must not contain symlinks: {', '.join(sorted(symlinks))}"
        )
    payload_files: dict[str, Path] = {}
    for path in paths:
        relative_path = path.relative_to(bundle_directory).as_posix()
        if path.is_file() and relative_path != "manifest.json":
            payload_files[relative_path] = path
    return payload_files


def _validate_summary_cross_references(
    *,
    bundle_directory: Path,
    summary_records: Sequence[dict[str, Any]],
    arm_ids: Sequence[str],
    expected_arms: Sequence[Mapping[str, Any]],
) -> None:
    expected_records = dict(zip(arm_ids, summary_records, strict=True))
    for arm_id in arm_ids:
        persisted = _load_json_mapping(
            bundle_directory / "summary" / f"{arm_id}.json",
            label="per-arm summary",
        )
        arm = persisted.get("arm")
        if (
            persisted.get("schema_version") != GATE1_RESULT_SCHEMA_VERSION
            or not isinstance(arm, Mapping)
            or arm.get("arm_id") != arm_id
            or persisted != expected_records[arm_id]
        ):
            raise ExperimentError(f"Gate 1 summary cross-reference mismatch for arm {arm_id}")

    aggregate = _load_json_mapping(
        bundle_directory / "summary" / "aggregate.json",
        label="aggregate summary",
    )
    groups = aggregate.get("groups")
    if aggregate.get("schema_version") != GATE1_RESULT_SCHEMA_VERSION or not isinstance(
        groups, list
    ):
        raise ExperimentError("Gate 1 aggregate summary schema validation failed")
    aggregate_arm_ids: list[str] = []
    for group in groups:
        if not isinstance(group, Mapping) or not isinstance(group.get("arm_ids"), list):
            raise ExperimentError("Gate 1 aggregate summary cross-reference validation failed")
        aggregate_arm_ids.extend(str(arm_id) for arm_id in group["arm_ids"])
    if (
        len(aggregate_arm_ids) != len(arm_ids)
        or set(aggregate_arm_ids) != set(arm_ids)
        or aggregate != aggregate_arm_summaries(summary_records, expected_arms=expected_arms)
    ):
        raise ExperimentError("Gate 1 aggregate summary cross-reference validation failed")

    try:
        with (bundle_directory / "summary" / "arms.csv").open(
            encoding="utf-8",
            newline="",
        ) as stream:
            csv_arm_ids = [str(row["arm_id"]) for row in csv.DictReader(stream)]
    except (KeyError, OSError) as error:
        raise ExperimentError("Gate 1 arms.csv validation failed") from error
    if csv_arm_ids != list(arm_ids):
        raise ExperimentError("Gate 1 arms.csv cross-reference validation failed")


def _validate_plot_cross_references(
    *,
    bundle_directory: Path,
    arm_ids: Sequence[str],
) -> None:
    from scripts.gate1_plots import PLOT_FILENAMES

    plot_manifest = _load_json_mapping(
        bundle_directory / "plots" / "manifest.json",
        label="plot manifest",
    )
    points = plot_manifest.get("points")
    line_series = plot_manifest.get("line_series")
    if (
        plot_manifest.get("schema_version") != GATE1_RESULT_SCHEMA_VERSION
        or plot_manifest.get("arm_ids") != list(arm_ids)
        or plot_manifest.get("plots") != sorted(PLOT_FILENAMES)
        or not isinstance(points, list)
        or not isinstance(line_series, list)
    ):
        raise ExperimentError("Gate 1 plot manifest schema validation failed")
    point_arm_ids = [str(point.get("arm_id")) for point in points if isinstance(point, Mapping)]
    if point_arm_ids != list(arm_ids) or len(point_arm_ids) != len(points):
        raise ExperimentError("Gate 1 plot manifest cross-reference validation failed")
    line_arm_ids: list[str] = []
    for series in line_series:
        if not isinstance(series, Mapping) or not isinstance(series.get("arm_ids"), list):
            raise ExperimentError("Gate 1 plot manifest cross-reference validation failed")
        line_arm_ids.extend(str(arm_id) for arm_id in series["arm_ids"])
    if len(line_arm_ids) != len(arm_ids) or set(line_arm_ids) != set(arm_ids):
        raise ExperimentError("Gate 1 plot manifest cross-reference validation failed")
    for filename in PLOT_FILENAMES:
        try:
            signature = (bundle_directory / "plots" / filename).read_bytes()[:8]
        except OSError as error:
            raise ExperimentError(f"Gate 1 plot validation failed: {filename}") from error
        if signature != b"\x89PNG\r\n\x1a\n":
            raise ExperimentError(f"Gate 1 plot validation failed: {filename}")


def validate_gate1_final_bundle(
    bundle_directory: Path,
    summary_records: Sequence[dict[str, Any]],
    *,
    expected_arms: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Re-read and verify a staged Gate 1 bundle before atomic publication."""
    from scripts.gate1_plots import PLOT_FILENAMES

    arm_ids = _arm_ids(summary_records)
    manifest = _load_json_mapping(
        bundle_directory / "manifest.json",
        label="final bundle manifest",
    )
    manifest_files = manifest.get("files")
    if (
        manifest.get("schema_version") != GATE1_FINAL_BUNDLE_SCHEMA_VERSION
        or manifest.get("result_schema_version") != GATE1_RESULT_SCHEMA_VERSION
        or manifest.get("status") != "complete"
        or manifest.get("hash_algorithm") != "sha256"
        or manifest.get("publication_method") != "same_filesystem_atomic_directory_rename"
        or manifest.get("arm_ids") != arm_ids
        or not isinstance(manifest_files, Mapping)
    ):
        raise ExperimentError("Gate 1 final bundle manifest schema validation failed")
    if not all(isinstance(path, str) for path in manifest_files):
        raise ExperimentError("Gate 1 final bundle manifest file paths are invalid")
    for relative_path in manifest_files:
        assert isinstance(relative_path, str)
        candidate = Path(relative_path)
        if (
            candidate.is_absolute()
            or ".." in candidate.parts
            or candidate.as_posix() != relative_path
        ):
            raise ExperimentError(f"Gate 1 final bundle manifest path is unsafe: {relative_path}")

    payload_files = _payload_files(bundle_directory)
    declared_file_count = manifest.get("file_count")
    if (
        type(declared_file_count) is not int
        or declared_file_count != len(manifest_files)
        or declared_file_count != len(payload_files)
        or set(manifest_files) != set(payload_files)
    ):
        raise ExperimentError("Gate 1 final bundle file count validation failed")

    required_paths = {
        *(f"summary/{arm_id}.json" for arm_id in arm_ids),
        "summary/aggregate.json",
        "summary/arms.csv",
        "plots/manifest.json",
        *(f"plots/{filename}" for filename in PLOT_FILENAMES),
    }
    non_raw_paths = {
        relative_path for relative_path in payload_files if not relative_path.startswith("raw/")
    }
    if non_raw_paths != required_paths:
        raise ExperimentError("Gate 1 final bundle required file count validation failed")

    raw_directory = bundle_directory / "raw"
    try:
        raw_children = list(raw_directory.iterdir())
    except OSError as error:
        raise ExperimentError("Gate 1 raw artifact validation failed") from error
    raw_arm_ids = {path.name for path in raw_children if path.is_dir() and not path.is_symlink()}
    if (
        len(raw_children) != len(raw_arm_ids)
        or raw_arm_ids != set(arm_ids)
        or any(
            not any(path.is_file() for path in (raw_directory / arm_id).rglob("*"))
            for arm_id in arm_ids
        )
    ):
        raise ExperimentError("Gate 1 raw artifact cross-reference validation failed")

    _validate_summary_cross_references(
        bundle_directory=bundle_directory,
        summary_records=summary_records,
        arm_ids=arm_ids,
        expected_arms=expected_arms,
    )
    _validate_plot_cross_references(
        bundle_directory=bundle_directory,
        arm_ids=arm_ids,
    )

    for relative_path, path in payload_files.items():
        metadata = manifest_files[relative_path]
        if not isinstance(metadata, Mapping):
            raise ExperimentError(f"Gate 1 final bundle hash metadata is invalid: {relative_path}")
        expected_sha256 = metadata.get("sha256")
        expected_size = metadata.get("size_bytes")
        if (
            not isinstance(expected_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
            or type(expected_size) is not int
            or expected_size < 0
        ):
            raise ExperimentError(f"Gate 1 final bundle hash metadata is invalid: {relative_path}")
        try:
            observed_size = path.stat().st_size
            observed_sha256 = sha256_file(path)
        except OSError as error:
            raise ExperimentError(
                f"Gate 1 final bundle SHA-256 validation failed: {relative_path}"
            ) from error
        if observed_size != expected_size or observed_sha256 != expected_sha256:
            raise ExperimentError(f"Gate 1 final bundle SHA-256 validation failed: {relative_path}")
    return dict(manifest)


def _write_summary_csv(
    path: Path,
    summary_records: Sequence[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "arm_id",
                "workload",
                "workers",
                "repetition",
                "valid_for_capacity_comparison",
                "throughput_cases_per_second",
                "case_latency_p95_ms",
                "case_latency_p99_ms",
                "end_to_end_ms",
                "collector_missed_samples",
            ),
        )
        writer.writeheader()
        for record in summary_records:
            arm = record["arm"]
            summary = record["summary"]
            writer.writerow(
                {
                    "arm_id": arm["arm_id"],
                    "workload": arm["workload"],
                    "workers": arm["workers"],
                    "repetition": arm["repetition"],
                    "valid_for_capacity_comparison": summary["valid_for_capacity_comparison"],
                    "throughput_cases_per_second": summary["throughput_cases_per_second"],
                    "case_latency_p95_ms": summary["case_latency_ms"]["p95"],
                    "case_latency_p99_ms": summary["case_latency_ms"]["p99"],
                    "end_to_end_ms": summary["end_to_end_ms"],
                    "collector_missed_samples": summary.get("collector_missed_samples"),
                }
            )


def _build_staged_bundle(
    *,
    run_directory: Path,
    staging_directory: Path,
    summary_records: Sequence[dict[str, Any]],
    arm_ids: Sequence[str],
    expected_arms: Sequence[Mapping[str, Any]],
) -> None:
    from scripts.gate1_plots import generate_gate1_plots

    raw_directory = run_directory / "raw"
    if raw_directory.is_symlink():
        raise ExperimentError("Gate 1 raw artifact directory must not be a symlink")
    shutil.copytree(raw_directory, staging_directory / "raw", symlinks=True)
    for arm_id in arm_ids:
        source_summary = run_directory / "summary" / f"{arm_id}.json"
        if source_summary.is_symlink() or not source_summary.is_file():
            raise ExperimentError(f"Gate 1 per-arm summary is invalid: {arm_id}")
        staged_summary = staging_directory / "summary" / f"{arm_id}.json"
        staged_summary.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_summary, staged_summary)

    write_report(
        staging_directory / "summary" / "aggregate.json",
        aggregate_arm_summaries(summary_records, expected_arms=expected_arms),
    )
    _write_summary_csv(
        staging_directory / "summary" / "arms.csv",
        summary_records,
    )
    generate_gate1_plots(summary_records, staging_directory / "plots")

    payload_files = _payload_files(staging_directory)
    write_report(
        staging_directory / "manifest.json",
        {
            "schema_version": GATE1_FINAL_BUNDLE_SCHEMA_VERSION,
            "result_schema_version": GATE1_RESULT_SCHEMA_VERSION,
            "status": "complete",
            "hash_algorithm": "sha256",
            "publication_method": "same_filesystem_atomic_directory_rename",
            "arm_ids": list(arm_ids),
            "file_count": len(payload_files),
            "files": {
                relative_path: {
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
                for relative_path, path in sorted(payload_files.items())
            },
        },
    )


def finalize_gate1_run_evidence(
    run_directory: Path,
    summary_records: Sequence[dict[str, Any]],
    *,
    expected_arms: Sequence[Mapping[str, Any]],
    staging_parent: Path | None = None,
) -> None:
    """Stage, validate, and atomically publish one complete Gate 1 evidence bundle."""
    arm_ids = _arm_ids(summary_records)
    aggregate_arm_summaries(summary_records, expected_arms=expected_arms)
    final_directory = run_directory / GATE1_FINAL_DIRECTORY_NAME
    if final_directory.exists() or final_directory.is_symlink():
        raise ExperimentError(
            f"refusing to overwrite existing Gate 1 final evidence: {final_directory}"
        )
    selected_staging_parent = staging_parent or run_directory
    if not run_directory.is_dir() or not selected_staging_parent.is_dir():
        raise ExperimentError("Gate 1 finalization directories must already exist")
    try:
        final_device = os.stat(run_directory).st_dev
        staging_device = os.stat(selected_staging_parent).st_dev
    except OSError as error:
        raise ExperimentError("unable to inspect Gate 1 finalization filesystem") from error
    if final_device != staging_device:
        raise ExperimentError("Gate 1 staging and final directories must be on the same filesystem")

    lock_directory = run_directory / GATE1_FINALIZATION_LOCK_NAME
    try:
        lock_directory.mkdir()
    except FileExistsError as error:
        raise ExperimentError("Gate 1 finalization is already in progress") from error

    staging_directory: Path | None = None
    try:
        if final_directory.exists() or final_directory.is_symlink():
            raise ExperimentError(
                f"refusing to overwrite existing Gate 1 final evidence: {final_directory}"
            )
        staging_directory = Path(
            tempfile.mkdtemp(
                prefix=".gate1-final-",
                dir=selected_staging_parent,
            )
        )
        try:
            _build_staged_bundle(
                run_directory=run_directory,
                staging_directory=staging_directory,
                summary_records=summary_records,
                arm_ids=arm_ids,
                expected_arms=expected_arms,
            )
            validate_gate1_final_bundle(
                staging_directory,
                summary_records,
                expected_arms=expected_arms,
            )
            if final_directory.exists() or final_directory.is_symlink():
                raise ExperimentError(
                    f"refusing to overwrite existing Gate 1 final evidence: {final_directory}"
                )
            try:
                staging_directory.rename(final_directory)
            except OSError as error:
                raise ExperimentError("Gate 1 final bundle atomic publication failed") from error
        finally:
            if staging_directory.exists():
                shutil.rmtree(staging_directory)
    finally:
        lock_directory.rmdir()
