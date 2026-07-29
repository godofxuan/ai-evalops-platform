import json
import re
import subprocess
from pathlib import Path
from types import TracebackType
from typing import Any, TextIO

from prometheus_client.parser import text_string_to_metric_families

from scripts.gate1_preflight import collect_compose_service_rows


class CollectorParseError(ValueError):
    """A collector sample cannot be normalized without inventing data."""


class JsonlEvidenceWriter:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._stream: TextIO = path.open("x", encoding="utf-8", newline="\n")

    def append(self, sample: dict[str, Any]) -> None:
        self._stream.write(json.dumps(sample, separators=(",", ":"), ensure_ascii=False) + "\n")
        self._stream.flush()

    def close(self) -> None:
        self._stream.close()

    def __enter__(self) -> "JsonlEvidenceWriter":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()


_SIZE_MULTIPLIERS = {
    "B": 1,
    "kB": 1_000,
    "KB": 1_000,
    "KiB": 1_024,
    "MB": 1_000_000,
    "MiB": 1_048_576,
    "GB": 1_000_000_000,
    "GiB": 1_073_741_824,
}


def _parse_memory_size(value: str) -> int:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+)\s*", value)
    if match is None or match.group(2) not in _SIZE_MULTIPLIERS:
        raise CollectorParseError(f"unsupported memory size: {value}")
    return round(float(match.group(1)) * _SIZE_MULTIPLIERS[match.group(2)])


def parse_docker_stats(line: str) -> dict[str, Any]:
    """Normalize one Docker stats JSON line while retaining source strings."""
    try:
        payload = json.loads(line)
        container = str(payload["Container"])
        raw_cpu = str(payload["CPUPerc"])
        raw_memory = str(payload["MemUsage"])
        raw_memory_percent = str(payload["MemPerc"])
        usage, limit = raw_memory.split("/", maxsplit=1)
        cpu_percent = float(raw_cpu.removesuffix("%"))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise CollectorParseError("invalid Docker stats JSON sample") from error
    return {
        "container": container,
        "cpu_percent": cpu_percent,
        "rss_bytes": _parse_memory_size(usage),
        "memory_limit_bytes": _parse_memory_size(limit),
        "raw": {
            "cpu_percent": raw_cpu,
            "memory_usage": raw_memory,
            "memory_percent": raw_memory_percent,
        },
    }


def collect_docker_stats_snapshot(*, compose_file: Path) -> list[dict[str, Any]]:
    container_ids = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "ps",
            "--quiet",
            "api",
            "worker",
            "reaper",
            "postgres",
            "redis",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if not container_ids:
        raise CollectorParseError("Compose returned no experiment containers")
    stats = subprocess.run(
        [
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{json .}}",
            *container_ids,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return [parse_docker_stats(line) for line in stats.stdout.splitlines() if line.strip()]


def collect_prometheus_snapshot(*, compose_file: Path) -> dict[str, str]:
    snapshots: dict[str, str] = {}
    metrics_ports = {"api": 8000, "worker": 9101, "reaper": 9102}
    for service in collect_compose_service_rows(compose_file=compose_file):
        service_name = service.get("Service", "")
        container_id = service.get("ID", "")
        if service_name not in metrics_ports or not container_id:
            continue
        port = metrics_ports[service_name]
        probe = (
            "from urllib.request import urlopen;"
            f"print(urlopen('http://127.0.0.1:{port}/metrics',timeout=2)"
            ".read().decode('utf-8'),end='')"
        )
        result = subprocess.run(
            ["docker", "exec", container_id, "python", "-c", probe],
            check=True,
            capture_output=True,
            text=True,
        )
        snapshots[f"{service_name}-{container_id[:12]}"] = result.stdout
    if not snapshots:
        raise CollectorParseError("Compose returned no scrapeable app containers")
    return snapshots


def write_prometheus_snapshot(
    *,
    directory: Path,
    phase: str,
    snapshots: dict[str, str],
) -> None:
    phase_directory = directory / "prometheus" / phase
    phase_directory.mkdir(parents=True, exist_ok=False)
    for container, text in snapshots.items():
        (phase_directory / f"{container}.prom").write_text(
            text,
            encoding="utf-8",
            newline="\n",
        )


type PrometheusSampleKey = tuple[str, tuple[tuple[str, str], ...]]


def parse_prometheus_samples(text: str) -> dict[PrometheusSampleKey, float]:
    samples: dict[PrometheusSampleKey, float] = {}
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            labels = tuple(sorted((str(key), str(value)) for key, value in sample.labels.items()))
            samples[(sample.name, labels)] = float(sample.value)
    return samples


def summarize_prometheus_deltas(
    *,
    before: dict[str, str],
    after: dict[str, str],
) -> dict[str, Any]:
    if set(before) != set(after):
        raise CollectorParseError("Prometheus before/after container identities do not match")
    operation_totals: dict[str, dict[str, Any]] = {
        operation: {"count": 0.0, "sum_seconds": 0.0, "buckets": {}}
        for operation in ("claim", "result", "failure", "reaper")
    }
    redis_delta = 0.0
    for container in sorted(before):
        before_samples = parse_prometheus_samples(before[container])
        after_samples = parse_prometheus_samples(after[container])
        keys = set(before_samples) | set(after_samples)
        for key in keys:
            metric_name, labels = key
            delta = after_samples.get(key, 0.0) - before_samples.get(key, 0.0)
            if delta < 0:
                raise CollectorParseError(f"Prometheus cumulative sample decreased for {container}")
            label_map = dict(labels)
            operation = label_map.get("operation")
            if metric_name == "redis_publish_failures_total":
                redis_delta += delta
            elif operation is not None and metric_name.startswith("db_operation_duration_seconds_"):
                aggregate = operation_totals.setdefault(
                    operation,
                    {"count": 0.0, "sum_seconds": 0.0, "buckets": {}},
                )
                if metric_name.endswith("_count"):
                    aggregate["count"] += delta
                elif metric_name.endswith("_sum"):
                    aggregate["sum_seconds"] += delta
                elif metric_name.endswith("_bucket"):
                    boundary = label_map["le"]
                    buckets = aggregate["buckets"]
                    buckets[boundary] = buckets.get(boundary, 0.0) + delta
    db_operations = {}
    for operation, aggregate in operation_totals.items():
        count = float(aggregate["count"])
        sum_seconds = float(aggregate["sum_seconds"])
        db_operations[operation] = {
            "evidence": "DIRECTIONAL" if count > 0 else "VERIFIED",
            "count": count,
            "sum_seconds": sum_seconds,
            "mean_ms": sum_seconds * 1000 / count if count > 0 else None,
            "buckets": aggregate["buckets"],
        }
    return {
        "db_operations": db_operations,
        "redis_publish_failures": {
            "evidence": "VERIFIED",
            "delta": redis_delta,
        },
    }
