import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from scripts.experiment_support import ExperimentError

PLOT_FILENAMES = (
    "throughput.png",
    "latency.png",
    "queue_and_claim.png",
    "database.png",
    "cpu_and_rss.png",
)
RENDER_DPI = 144


def _value(mapping: dict[str, Any], *keys: str) -> float | None:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    if isinstance(current, int | float):
        return float(current)
    return None


def _point(record: dict[str, Any]) -> dict[str, Any]:
    arm = record["arm"]
    summary = record["summary"]
    resources = summary.get("cpu_rss_by_container", {})
    cpu_peaks = [
        float(container["cpu_percent_peak"])
        for container in resources.values()
        if container.get("cpu_percent_peak") is not None
    ]
    rss_peaks = [
        int(container["rss_bytes_peak"])
        for container in resources.values()
        if container.get("rss_bytes_peak") is not None
    ]
    return {
        "arm_id": str(arm["arm_id"]),
        "workload": str(arm["workload"]),
        "workers": int(arm["workers"]),
        "repetition": int(arm["repetition"]),
        "valid_for_capacity_comparison": bool(summary["valid_for_capacity_comparison"]),
        "throughput_cases_per_second": summary.get("throughput_cases_per_second"),
        "end_to_end_ms": summary.get("end_to_end_ms"),
        "case_latency_ms": summary.get("case_latency_ms"),
        "queue_wait_ms": summary.get("queue_wait_ms"),
        "retry_queue_wait_ms": summary.get("retry_queue_wait_ms"),
        "claim_latency_ms": summary.get("claim_latency_ms"),
        "db_lock_wait": summary.get("db_lock_wait"),
        "postgres_connections": summary.get("postgres_connections"),
        "cpu_percent_peak": max(cpu_peaks) if cpu_peaks else None,
        "rss_bytes_peak": max(rss_peaks) if rss_peaks else None,
        "resource_containers": sorted(resources),
    }


def _new_figure(
    *,
    title: str,
    y_label: str,
) -> tuple[Figure, Axes]:
    figure, axes = plt.subplots(figsize=(10, 6), constrained_layout=True)
    axes.set_title(title)
    axes.set_xlabel("Worker replicas")
    axes.set_ylabel(y_label)
    axes.grid(alpha=0.25)
    return figure, axes


def _ordered_line_series(
    points: Sequence[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    keys = sorted({(str(point["workload"]), int(point["repetition"])) for point in points})
    return [
        sorted(
            [
                point
                for point in points
                if (str(point["workload"]), int(point["repetition"])) == key
            ],
            key=lambda point: int(point["workers"]),
        )
        for key in keys
    ]


def _plot_series(
    axes: Axes,
    points: Sequence[dict[str, Any]],
    *,
    label: str,
    selector: Callable[[dict[str, Any]], float | None],
    marker: str,
    linestyle: str = "-",
) -> bool:
    plotted = False
    for line_points in _ordered_line_series(points):
        workload_points = [
            (int(point["workers"]), value)
            for point in line_points
            if (value := selector(point)) is not None
        ]
        if not workload_points:
            continue
        workload = str(line_points[0]["workload"])
        repetition = int(line_points[0]["repetition"])
        axes.plot(
            [workers for workers, _ in workload_points],
            [value for _, value in workload_points],
            marker=marker,
            linestyle=linestyle,
            alpha=0.75,
            label=f"{workload} r{repetition}: {label}",
        )
        axes.set_xticks(sorted({int(point["workers"]) for point in points}))
        plotted = True
    return plotted


def _select(*keys: str) -> Callable[[dict[str, Any]], float | None]:
    return lambda point: _value(point, *keys)


def _rss_mib(point: dict[str, Any]) -> float | None:
    rss_bytes = _value(point, "rss_bytes_peak")
    return None if rss_bytes is None else rss_bytes / (1024 * 1024)


def _finish_figure(figure: Figure, axes: Axes, path: Path, *, has_data: bool) -> None:
    if has_data:
        axes.legend(fontsize="small")
    else:
        axes.text(
            0.5,
            0.5,
            "UNKNOWN — required evidence was not collected",
            ha="center",
            va="center",
            transform=axes.transAxes,
        )
    with path.open("xb") as stream:
        figure.savefig(stream, format="png", dpi=RENDER_DPI)
    plt.close(figure)


def _throughput(points: Sequence[dict[str, Any]], path: Path) -> None:
    figure, axes = _new_figure(
        title="Gate 1 throughput — every repetition",
        y_label="Terminal cases / second",
    )
    has_data = _plot_series(
        axes,
        points,
        label="throughput",
        selector=lambda point: _value(point, "throughput_cases_per_second"),
        marker="o",
    )
    _finish_figure(figure, axes, path, has_data=has_data)


def _latency(points: Sequence[dict[str, Any]], path: Path) -> None:
    figure, case_axes = _new_figure(
        title="Gate 1 case and end-to-end latency — every repetition",
        y_label="Case latency (ms)",
    )
    end_to_end_axes = case_axes.twinx()
    end_to_end_axes.set_ylabel("End-to-end duration (ms)")
    has_case_data = False
    for percentile, marker in (("p50", "o"), ("p95", "s"), ("p99", "^")):
        has_case_data |= _plot_series(
            case_axes,
            points,
            label=f"case latency {percentile}",
            selector=_select("case_latency_ms", percentile),
            marker=marker,
        )
    has_end_to_end_data = _plot_series(
        end_to_end_axes,
        points,
        label="end-to-end",
        selector=lambda point: _value(point, "end_to_end_ms"),
        marker="x",
        linestyle="--",
    )
    if has_case_data:
        case_axes.legend(loc="upper left", fontsize="small")
    if has_end_to_end_data:
        end_to_end_axes.legend(loc="upper right", fontsize="small")
    if not has_case_data and not has_end_to_end_data:
        case_axes.text(
            0.5,
            0.5,
            "UNKNOWN — required evidence was not collected",
            ha="center",
            va="center",
            transform=case_axes.transAxes,
        )
    with path.open("xb") as stream:
        figure.savefig(stream, format="png", dpi=RENDER_DPI)
    plt.close(figure)


def _queue_and_claim(points: Sequence[dict[str, Any]], path: Path) -> None:
    figure, axes = _new_figure(
        title="Gate 1 queue and claim latency — every repetition",
        y_label="Milliseconds",
    )
    has_data = False
    for field, label, marker in (
        ("queue_wait_ms", "first queue wait p95", "o"),
        ("retry_queue_wait_ms", "retry queue wait p95", "s"),
        ("claim_latency_ms", "claim p95", "^"),
    ):
        has_data |= _plot_series(
            axes,
            points,
            label=label,
            selector=_select(field, "p95"),
            marker=marker,
        )
    _finish_figure(figure, axes, path, has_data=has_data)


def _database(points: Sequence[dict[str, Any]], path: Path) -> None:
    figure, axes = _new_figure(
        title="Gate 1 sampled database pressure — every repetition",
        y_label="Connections",
    )
    has_data = _plot_series(
        axes,
        points,
        label="sampled lock waiters (directional)",
        selector=lambda point: _value(point, "db_lock_wait", "peak_waiting_connections"),
        marker="o",
    )
    has_data |= _plot_series(
        axes,
        points,
        label="PostgreSQL connections",
        selector=lambda point: _value(point, "postgres_connections", "peak"),
        marker="s",
    )
    _finish_figure(figure, axes, path, has_data=has_data)


def _cpu_and_rss(points: Sequence[dict[str, Any]], path: Path) -> None:
    figure, cpu_axes = _new_figure(
        title="Gate 1 per-container resource peaks — every repetition",
        y_label="Peak CPU percent",
    )
    rss_axes = cpu_axes.twinx()
    rss_axes.set_ylabel("Peak RSS MiB")
    rss_axes.ticklabel_format(axis="y", style="plain", useOffset=False)
    has_cpu = _plot_series(
        cpu_axes,
        points,
        label="maximum container CPU",
        selector=lambda point: _value(point, "cpu_percent_peak"),
        marker="o",
    )
    has_rss = _plot_series(
        rss_axes,
        points,
        label="maximum container RSS",
        selector=_rss_mib,
        marker="s",
        linestyle="--",
    )
    if has_cpu:
        cpu_axes.legend(loc="upper left", fontsize="small")
    if has_rss:
        rss_axes.legend(loc="upper right", fontsize="small")
    if not has_cpu and not has_rss:
        cpu_axes.text(
            0.5,
            0.5,
            "UNKNOWN — required evidence was not collected",
            ha="center",
            va="center",
            transform=cpu_axes.transAxes,
        )
    with path.open("xb") as stream:
        figure.savefig(stream, format="png", dpi=RENDER_DPI)
    plt.close(figure)


def generate_gate1_plots(
    summary_records: Sequence[dict[str, Any]],
    output_directory: Path,
) -> dict[str, Any]:
    """Create the complete Gate 1 PNG bundle and its machine-auditable manifest."""
    output_directory.mkdir(parents=True, exist_ok=True)
    output_paths = [output_directory / filename for filename in (*PLOT_FILENAMES, "manifest.json")]
    conflicts = [path.name for path in output_paths if path.exists()]
    if conflicts:
        raise ExperimentError(
            f"refusing to overwrite existing Gate 1 plot evidence: {', '.join(conflicts)}"
        )
    points = [_point(record) for record in summary_records]
    line_series = _ordered_line_series(points)
    renderers = (
        ("throughput.png", _throughput),
        ("latency.png", _latency),
        ("queue_and_claim.png", _queue_and_claim),
        ("database.png", _database),
        ("cpu_and_rss.png", _cpu_and_rss),
    )
    for filename, renderer in renderers:
        renderer(points, output_directory / filename)
    manifest = {
        "schema_version": 1,
        "arm_ids": [str(point["arm_id"]) for point in points],
        "plots": sorted(PLOT_FILENAMES),
        "renderer": {
            "library": "matplotlib",
            "version": matplotlib.__version__,
            "backend": str(matplotlib.get_backend()),
            "dpi": RENDER_DPI,
        },
        "points": points,
        "line_series": [
            {
                "workload": str(series[0]["workload"]),
                "repetition": int(series[0]["repetition"]),
                "arm_ids": [str(point["arm_id"]) for point in series],
            }
            for series in line_series
        ],
    }
    manifest_path = output_directory / "manifest.json"
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return manifest
