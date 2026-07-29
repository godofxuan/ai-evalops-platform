import json
from copy import deepcopy
from pathlib import Path

import matplotlib
import pytest

from scripts.experiment_support import ExperimentError
from scripts.gate1_plots import generate_gate1_plots
from scripts.run_load_test import finalize_gate1_run_evidence


def _summary_records() -> list[dict[str, object]]:
    return [
        {
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
                        "cpu_percent_peak": 20.0 + workers,
                        "rss_bytes_peak": 100_000_000 + workers,
                    }
                },
            },
        }
        for workers in (1, 2)
    ]


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


def test_gate1_plot_bundle_refuses_any_partial_overwrite(tmp_path: Path) -> None:
    output_directory = tmp_path / "plots"
    output_directory.mkdir()
    existing_plot = output_directory / "database.png"
    existing_plot.write_bytes(b"prior evidence")

    with pytest.raises(ExperimentError, match="refusing to overwrite"):
        generate_gate1_plots([], output_directory)

    assert existing_plot.read_bytes() == b"prior evidence"
    assert list(output_directory.iterdir()) == [existing_plot]


def test_gate1_finalization_writes_tables_and_required_plots_together(
    tmp_path: Path,
) -> None:
    (tmp_path / "summary").mkdir()
    (tmp_path / "plots").mkdir()

    finalize_gate1_run_evidence(tmp_path, _summary_records())

    assert (tmp_path / "summary" / "aggregate.json").is_file()
    assert (tmp_path / "summary" / "arms.csv").is_file()
    assert (tmp_path / "plots" / "manifest.json").is_file()
    assert len(list((tmp_path / "plots").glob("*.png"))) == 5


def test_gate1_finalization_preflights_every_table_and_plot_before_writing(
    tmp_path: Path,
) -> None:
    summary_directory = tmp_path / "summary"
    plot_directory = tmp_path / "plots"
    summary_directory.mkdir()
    plot_directory.mkdir()
    existing_plot = plot_directory / "database.png"
    existing_plot.write_bytes(b"prior evidence")

    with pytest.raises(ExperimentError, match="refusing to overwrite"):
        finalize_gate1_run_evidence(tmp_path, _summary_records())

    assert list(summary_directory.iterdir()) == []
    assert list(plot_directory.iterdir()) == [existing_plot]


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
