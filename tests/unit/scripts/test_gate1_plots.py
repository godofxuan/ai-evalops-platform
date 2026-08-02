import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier
from typing import Any

import matplotlib
import pytest
from matplotlib.figure import Figure

import scripts.gate1_finalization as gate1_finalization
from scripts.experiment_support import ExperimentError
from scripts.gate1_finalization import finalize_gate1_run_evidence
from scripts.gate1_plots import generate_gate1_plots


def _summary_records() -> list[dict[str, object]]:
    return [
        {
            "schema_version": 3,
            "arm": {
                "arm_id": f"io-w{workers}-r1",
                "workload": "io_latency_v1",
                "workers": workers,
                "repetition": 1,
            },
            "summary": {
                "valid_for_capacity_comparison": True,
                "throughput_cases_per_second": 8.0 * workers,
                "end_to_end_ms": 60_000.0 / workers,
                "case_latency_ms": {
                    "evidence": "VERIFIED",
                    "p50": 30.0,
                    "p95": 45.0 + workers,
                    "p99": 55.0 + workers,
                },
                "queue_wait_ms": {
                    "evidence": "VERIFIED",
                    "p50": 5.0,
                    "p95": 8.0 + workers,
                    "p99": 10.0 + workers,
                },
                "retry_queue_wait_ms": {
                    "evidence": "VERIFIED",
                    "p50": 0.0,
                    "p95": 2.0,
                    "p99": 3.0,
                },
                "claim_latency_ms": {
                    "evidence": "VERIFIED",
                    "p50": 1.0,
                    "p95": 2.0 + workers,
                    "p99": 3.0 + workers,
                },
                "db_lock_wait": {
                    "evidence": "DIRECTIONAL",
                    "peak_waiting_connections": workers - 1,
                },
                "postgres_connections": {
                    "evidence": "VERIFIED",
                    "peak": 4 + workers,
                },
                "cpu_rss_by_container": {
                    "worker-1": {
                        "sample_count": 3,
                        "cpu_percent_peak": 900.0,
                        "rss_bytes_peak": 900_000_000,
                    }
                },
                "worker_cluster_resources": {
                    "status": "VERIFIED",
                    "worker_containers": [f"worker-{index}" for index in range(1, workers + 1)],
                    "cpu_percent": {"peak": 20.0 + workers},
                    "rss_bytes": {"peak": 100_000_000 + workers},
                },
            },
        }
        for workers in (1, 2)
    ]


def _write_working_evidence(
    run_directory: Path,
    records: list[dict[str, object]],
) -> None:
    (run_directory / "plots").mkdir()
    for record in records:
        arm = record["arm"]
        assert isinstance(arm, dict)
        arm_id = str(arm["arm_id"])
        raw_directory = run_directory / "raw" / arm_id
        raw_directory.mkdir(parents=True)
        (raw_directory / "jobs.json").write_text(
            json.dumps({"arm_id": arm_id, "jobs": []}),
            encoding="utf-8",
        )
        summary_path = run_directory / "summary" / f"{arm_id}.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(record),
            encoding="utf-8",
        )


def _finalize(
    run_directory: Path,
    records: list[dict[str, object]],
    **kwargs: Any,
) -> None:
    finalize_gate1_run_evidence(
        run_directory,
        records,
        expected_arms=[record["arm"] for record in records],
        **kwargs,
    )


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _assert_no_finalization_transients(run_directory: Path) -> None:
    assert not [
        path.name for path in run_directory.iterdir() if path.name.startswith(".gate1-final-")
    ]
    assert not (run_directory / ".gate1-finalize.lock").exists()


@pytest.mark.parametrize(
    "failure_save_number, completed_plot_count",
    [(2, 1), (4, 3)],
    ids=["after-plot-1", "after-plot-3"],
)
def test_gate1_finalization_plot_failure_leaves_working_evidence_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_save_number: int,
    completed_plot_count: int,
) -> None:
    records = _summary_records()
    _write_working_evidence(tmp_path, records)
    before = _file_snapshot(tmp_path)
    original_savefig = Figure.savefig
    save_count = 0

    def fail_on_second_save(
        figure: Figure,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        nonlocal save_count
        save_count += 1
        if save_count == failure_save_number:
            raise OSError(f"injected failure after {completed_plot_count} plots")
        return original_savefig(figure, *args, **kwargs)

    monkeypatch.setattr(Figure, "savefig", fail_on_second_save)

    with pytest.raises(
        OSError,
        match=f"injected failure after {completed_plot_count} plots",
    ):
        _finalize(tmp_path, records)

    assert save_count == failure_save_number
    assert not (tmp_path / "final").exists()
    assert _file_snapshot(tmp_path) == before
    _assert_no_finalization_transients(tmp_path)


def test_gate1_finalization_summary_write_failure_leaves_no_formal_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _summary_records()
    _write_working_evidence(tmp_path, records)
    before = _file_snapshot(tmp_path)
    original_open = Path.open

    def fail_aggregate_write(path: Path, *args: Any, **kwargs: Any) -> Any:
        if (
            path.name == "aggregate.json.tmp"
            and path.parent.name == "summary"
            and any(part.startswith(".gate1-final-") for part in path.parts)
        ):
            raise OSError("injected summary write failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_aggregate_write)

    with pytest.raises(OSError, match="injected summary write failure"):
        _finalize(tmp_path, records)

    assert not (tmp_path / "final").exists()
    assert _file_snapshot(tmp_path) == before
    _assert_no_finalization_transients(tmp_path)


def test_gate1_finalization_plot_manifest_write_failure_leaves_no_formal_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _summary_records()
    _write_working_evidence(tmp_path, records)
    before = _file_snapshot(tmp_path)
    original_open = Path.open

    def fail_plot_manifest_write(path: Path, *args: Any, **kwargs: Any) -> Any:
        if (
            path.name == "manifest.json"
            and path.parent.name == "plots"
            and any(part.startswith(".gate1-final-") for part in path.parts)
        ):
            raise OSError("injected plot manifest write failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_plot_manifest_write)

    with pytest.raises(OSError, match="injected plot manifest write failure"):
        _finalize(tmp_path, records)

    assert not (tmp_path / "final").exists()
    assert _file_snapshot(tmp_path) == before
    _assert_no_finalization_transients(tmp_path)


def test_gate1_plot_bundle_preserves_every_arm_as_auditable_png_evidence(
    tmp_path: Path,
) -> None:
    records = _summary_records()
    output_directory = tmp_path / "plots"

    manifest = generate_gate1_plots(records, output_directory)

    expected_pngs = {
        "throughput.png",
        "latency.png",
        "queue_and_claim.png",
        "database.png",
        "cpu_and_rss.png",
    }
    assert {path.name for path in output_directory.glob("*.png")} == expected_pngs
    for filename in expected_pngs:
        content = (output_directory / filename).read_bytes()
        assert content.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(content) > 1_000
    persisted_manifest = json.loads(
        (output_directory / "manifest.json").read_text(encoding="utf-8")
    )
    assert persisted_manifest == manifest
    assert manifest["schema_version"] == 4
    assert manifest["arm_ids"] == ["io-w1-r1", "io-w2-r1"]
    assert manifest["plots"] == sorted(expected_pngs)
    assert manifest["renderer"] == {
        "library": "matplotlib",
        "version": matplotlib.__version__,
        "backend": "Agg",
        "dpi": 144,
    }
    assert [point["arm_id"] for point in manifest["points"]] == [
        "io-w1-r1",
        "io-w2-r1",
    ]
    assert manifest["points"][0]["db_lock_wait"]["evidence"] == "DIRECTIONAL"
    assert manifest["points"][0]["worker_cluster_cpu_percent_peak"] == 21.0
    assert manifest["points"][0]["worker_cluster_rss_bytes_peak"] == 100_000_001
    assert manifest["points"][0]["resource_containers"] == ["worker-1"]


def test_gate1_plot_bundle_refuses_any_partial_overwrite(tmp_path: Path) -> None:
    output_directory = tmp_path / "plots"
    output_directory.mkdir()
    existing_plot = output_directory / "database.png"
    existing_plot.write_bytes(b"prior evidence")

    with pytest.raises(ExperimentError, match="refusing to overwrite"):
        generate_gate1_plots([], output_directory)

    assert existing_plot.read_bytes() == b"prior evidence"
    assert list(output_directory.iterdir()) == [existing_plot]


def test_gate1_finalization_publishes_one_complete_hashed_bundle(
    tmp_path: Path,
) -> None:
    records = _summary_records()
    _write_working_evidence(tmp_path, records)

    finalize_gate1_run_evidence(
        tmp_path,
        records,
        expected_arms=[record["arm"] for record in records],
    )

    final_directory = tmp_path / "final"
    assert (final_directory / "raw" / "io-w1-r1" / "jobs.json").is_file()
    assert (final_directory / "raw" / "io-w2-r1" / "jobs.json").is_file()
    assert (final_directory / "summary" / "io-w1-r1.json").is_file()
    assert (final_directory / "summary" / "io-w2-r1.json").is_file()
    aggregate = json.loads(
        (final_directory / "summary" / "aggregate.json").read_text(encoding="utf-8")
    )
    assert aggregate["schema_version"] == 4
    assert aggregate["gate_evaluation"]["quality_gate"]["status"] == "VERIFIED"
    assert aggregate["gate_evaluation"]["adoption_gate"]["status"] == "NOT_RUN"
    assert (
        aggregate["gate_evaluation"]["adoption_gate"]["review_readiness"]
        == "READY_FOR_HUMAN_REVIEW"
    )
    assert aggregate["gate_evaluation"]["adoption_gate"]["selected_worker_count"] is None
    assert (final_directory / "summary" / "arms.csv").is_file()
    assert (final_directory / "plots" / "manifest.json").is_file()
    assert len(list((final_directory / "plots").glob("*.png"))) == 5

    manifest_path = final_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload_paths = {
        path.relative_to(final_directory).as_posix()
        for path in final_directory.rglob("*")
        if path.is_file() and path != manifest_path
    }
    assert manifest["schema_version"] == 1
    assert manifest["result_schema_version"] == 4
    assert manifest["status"] == "complete"
    assert manifest["hash_algorithm"] == "sha256"
    assert manifest["publication_method"] == "same_filesystem_atomic_directory_rename"
    assert manifest["arm_ids"] == ["io-w1-r1", "io-w2-r1"]
    assert manifest["file_count"] == len(payload_paths)
    assert set(manifest["files"]) == payload_paths
    for relative_path, metadata in manifest["files"].items():
        content = (final_directory / relative_path).read_bytes()
        assert metadata == {
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }


def test_gate1_finalization_refuses_an_existing_partial_formal_target(
    tmp_path: Path,
) -> None:
    records = _summary_records()
    _write_working_evidence(tmp_path, records)
    plot_directory = tmp_path / "final" / "plots"
    plot_directory.mkdir(parents=True)
    existing_plot = plot_directory / "database.png"
    existing_plot.write_bytes(b"prior evidence")
    before = _file_snapshot(tmp_path / "final")

    with pytest.raises(ExperimentError, match="refusing to overwrite"):
        _finalize(tmp_path, records)

    assert _file_snapshot(tmp_path / "final") == before
    _assert_no_finalization_transients(tmp_path)


def test_gate1_finalization_repeated_call_refuses_existing_complete_bundle(
    tmp_path: Path,
) -> None:
    records = _summary_records()
    _write_working_evidence(tmp_path, records)
    _finalize(tmp_path, records)
    before = _file_snapshot(tmp_path / "final")

    with pytest.raises(ExperimentError, match="refusing to overwrite"):
        _finalize(tmp_path, records)

    assert _file_snapshot(tmp_path / "final") == before
    _assert_no_finalization_transients(tmp_path)


def test_gate1_finalization_rejects_cross_filesystem_staging_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _summary_records()
    _write_working_evidence(tmp_path, records)
    foreign_staging_parent = tmp_path / "foreign-staging"
    foreign_staging_parent.mkdir()
    before = _file_snapshot(tmp_path)
    original_stat = os.stat

    def report_foreign_device(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        result = original_stat(path, *args, **kwargs)
        if Path(path) == foreign_staging_parent:
            values = list(result)
            values[2] = int(result.st_dev) + 1
            return os.stat_result(values)
        return result

    monkeypatch.setattr(os, "stat", report_foreign_device)

    with pytest.raises(ExperimentError, match="same filesystem"):
        _finalize(
            tmp_path,
            records,
            staging_parent=foreign_staging_parent,
        )

    assert not (tmp_path / "final").exists()
    assert _file_snapshot(tmp_path) == before
    _assert_no_finalization_transients(tmp_path)


def test_gate1_finalization_rehashes_every_payload_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _summary_records()
    _write_working_evidence(tmp_path, records)
    before = _file_snapshot(tmp_path)
    original_sha256_file = gate1_finalization.sha256_file
    target_hash_calls = 0

    def report_changed_hash(path: Path) -> str:
        nonlocal target_hash_calls
        observed = original_sha256_file(path)
        if path.name == "throughput.png" and any(
            part.startswith(".gate1-final-") for part in path.parts
        ):
            target_hash_calls += 1
            if target_hash_calls == 2:
                return "0" * 64
        return observed

    monkeypatch.setattr(gate1_finalization, "sha256_file", report_changed_hash)

    with pytest.raises(ExperimentError, match="SHA-256"):
        _finalize(tmp_path, records)

    assert target_hash_calls == 2
    assert not (tmp_path / "final").exists()
    assert _file_snapshot(tmp_path) == before
    _assert_no_finalization_transients(tmp_path)


def test_gate1_finalization_detects_incomplete_file_count_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _summary_records()
    _write_working_evidence(tmp_path, records)
    before = _file_snapshot(tmp_path)
    original_read_text = Path.read_text
    payload_removed = False

    def remove_payload_before_validation(
        path: Path,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        nonlocal payload_removed
        if (
            not payload_removed
            and path.name == "manifest.json"
            and any(part.startswith(".gate1-final-") for part in path.parts)
        ):
            (path.parent / "plots" / "throughput.png").unlink()
            payload_removed = True
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", remove_payload_before_validation)

    with pytest.raises(ExperimentError, match="file count"):
        _finalize(tmp_path, records)

    assert payload_removed
    assert not (tmp_path / "final").exists()
    assert _file_snapshot(tmp_path) == before
    _assert_no_finalization_transients(tmp_path)


def test_gate1_finalization_rejects_summary_arm_cross_reference_mismatch(
    tmp_path: Path,
) -> None:
    records = _summary_records()
    _write_working_evidence(tmp_path, records)
    mismatched = deepcopy(records[0])
    arm = mismatched["arm"]
    assert isinstance(arm, dict)
    arm["arm_id"] = "different-arm"
    (tmp_path / "summary" / "io-w1-r1.json").write_text(
        json.dumps(mismatched),
        encoding="utf-8",
    )
    before = _file_snapshot(tmp_path)

    with pytest.raises(ExperimentError, match="summary cross-reference"):
        _finalize(tmp_path, records)

    assert not (tmp_path / "final").exists()
    assert _file_snapshot(tmp_path) == before
    _assert_no_finalization_transients(tmp_path)


def test_gate1_finalization_rejects_per_arm_summary_schema_mismatch(
    tmp_path: Path,
) -> None:
    records = _summary_records()
    _write_working_evidence(tmp_path, records)
    outdated = deepcopy(records[0])
    outdated["schema_version"] = 1
    (tmp_path / "summary" / "io-w1-r1.json").write_text(
        json.dumps(outdated),
        encoding="utf-8",
    )
    before = _file_snapshot(tmp_path)

    with pytest.raises(ExperimentError, match="summary cross-reference"):
        _finalize(tmp_path, records)

    assert not (tmp_path / "final").exists()
    assert _file_snapshot(tmp_path) == before
    _assert_no_finalization_transients(tmp_path)


def test_gate1_finalization_concurrent_calls_publish_exactly_one_bundle(
    tmp_path: Path,
) -> None:
    records = _summary_records()
    _write_working_evidence(tmp_path, records)
    start = Barrier(2)

    def finalize_after_barrier() -> BaseException | None:
        start.wait()
        try:
            _finalize(tmp_path, records)
        except BaseException as error:
            return error
        return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: finalize_after_barrier(), range(2)))

    assert sum(outcome is None for outcome in outcomes) == 1
    failures = [outcome for outcome in outcomes if outcome is not None]
    assert len(failures) == 1
    assert isinstance(failures[0], ExperimentError)
    assert "already in progress" in str(failures[0]) or "refusing to overwrite" in str(failures[0])
    assert (tmp_path / "final" / "manifest.json").is_file()
    _assert_no_finalization_transients(tmp_path)


def test_gate1_plot_lines_never_connect_different_repetitions(tmp_path: Path) -> None:
    first_repetition = _summary_records()
    second_repetition = deepcopy(first_repetition)
    for record in second_repetition:
        arm = record["arm"]
        assert isinstance(arm, dict)
        arm["repetition"] = 2
        arm["arm_id"] = f"{arm['arm_id'][:-1]}2"
    randomized_input = [
        second_repetition[1],
        first_repetition[0],
        second_repetition[0],
        first_repetition[1],
    ]

    manifest = generate_gate1_plots(randomized_input, tmp_path / "plots")

    assert manifest["line_series"] == [
        {
            "workload": "io_latency_v1",
            "repetition": 1,
            "arm_ids": ["io-w1-r1", "io-w2-r1"],
        },
        {
            "workload": "io_latency_v1",
            "repetition": 2,
            "arm_ids": ["io-w1-r2", "io-w2-r2"],
        },
    ]
