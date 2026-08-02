import json
import math
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, TextIO

from prometheus_client.parser import text_string_to_metric_families

from scripts.gate1_preflight import collect_compose_service_rows

PROMETHEUS_EVIDENCE_SCHEMA_VERSION = 2


class CollectorParseError(ValueError):
    """A collector sample cannot be normalized without inventing data."""


@dataclass(frozen=True, slots=True)
class PrometheusScrape:
    status: Literal["COLLECTED", "COLLECTION_FAILED"]
    text: str | None
    reason: str | None


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
        container_id = str(payload["ID"]).strip()
        container = str(payload["Name"]).strip()
        raw_cpu = str(payload["CPUPerc"])
        raw_memory = str(payload["MemUsage"])
        raw_memory_percent = str(payload["MemPerc"])
        usage, limit = raw_memory.split("/", maxsplit=1)
        cpu_percent = float(raw_cpu.removesuffix("%"))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise CollectorParseError("invalid Docker stats JSON sample") from error
    if not container_id or not container or not math.isfinite(cpu_percent) or cpu_percent < 0:
        raise CollectorParseError("invalid Docker stats container identity or CPU sample")
    return {
        "container_id": container_id,
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
    experiment_services = {"api", "worker", "reaper", "postgres", "redis"}
    compose_rows = [
        row
        for row in collect_compose_service_rows(compose_file=compose_file)
        if str(row.get("Service", "")) in experiment_services
    ]
    if not compose_rows:
        raise CollectorParseError("Compose returned no experiment containers")
    containers: dict[str, dict[str, str]] = {}
    for row in compose_rows:
        container_id = str(row.get("ID", "")).strip()
        container_name = str(row.get("Name", "")).strip()
        service = str(row.get("Service", "")).strip()
        if not container_id or not container_name or not service:
            raise CollectorParseError("Compose returned incomplete container identity")
        if container_id in containers:
            raise CollectorParseError("Compose returned duplicate container identity")
        containers[container_id] = {"name": container_name, "service": service}

    stats = subprocess.run(
        [
            "docker",
            "stats",
            "--no-stream",
            "--no-trunc",
            "--format",
            "{{json .}}",
            *containers,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    samples: list[dict[str, Any]] = []
    observed_ids: set[str] = set()
    for line in stats.stdout.splitlines():
        if not line.strip():
            continue
        sample = parse_docker_stats(line)
        sample_id = str(sample["container_id"])
        matching_ids = [
            container_id
            for container_id in containers
            if container_id == sample_id
            or container_id.startswith(sample_id)
            or sample_id.startswith(container_id)
        ]
        if len(matching_ids) != 1:
            raise CollectorParseError("Docker stats container identity is not uniquely bound")
        compose_id = matching_ids[0]
        if compose_id in observed_ids:
            raise CollectorParseError("Docker stats returned duplicate container sample")
        identity = containers[compose_id]
        if sample["container"] != identity["name"]:
            raise CollectorParseError("Docker stats container name does not match Compose")
        observed_ids.add(compose_id)
        sample["service"] = identity["service"]
        samples.append(sample)
    if observed_ids != set(containers):
        raise CollectorParseError("Docker stats omitted a Compose experiment container")
    return samples


def collect_prometheus_snapshot(*, compose_file: Path) -> dict[str, PrometheusScrape]:
    snapshots: dict[str, PrometheusScrape] = {}
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
        source = f"{service_name}-{container_id[:12]}"
        try:
            result = subprocess.run(
                ["docker", "exec", container_id, "python", "-c", probe],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.SubprocessError):
            snapshots[source] = PrometheusScrape(
                status="COLLECTION_FAILED",
                text=None,
                reason="endpoint_request_failed",
            )
        else:
            snapshots[source] = PrometheusScrape(
                status="COLLECTED",
                text=result.stdout,
                reason=None,
            )
    if not snapshots:
        raise CollectorParseError("Compose returned no scrapeable app containers")
    return snapshots


def write_prometheus_snapshot(
    *,
    directory: Path,
    phase: str,
    snapshots: Mapping[str, str | PrometheusScrape],
) -> None:
    phase_directory = directory / "prometheus" / phase
    phase_directory.mkdir(parents=True, exist_ok=False)
    failures: dict[str, str] = {}
    for container, value in snapshots.items():
        scrape = _prometheus_scrape(value)
        if scrape.status == "COLLECTION_FAILED":
            failures[container] = scrape.reason or "collection_failed"
            continue
        if scrape.text is None:
            failures[container] = "scrape_payload_missing"
            continue
        (phase_directory / f"{container}.prom").write_text(
            scrape.text,
            encoding="utf-8",
            newline="\n",
        )
    if failures:
        (phase_directory / "collection_failures.json").write_text(
            json.dumps(failures, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )


type PrometheusSampleKey = tuple[str, tuple[tuple[str, str], ...]]
type PrometheusSnapshotValue = str | PrometheusScrape

_DB_OPERATIONS = ("claim", "result", "failure", "reaper")
_REQUIRED_DB_OPERATIONS = frozenset({"claim", "result"})
_DB_HISTOGRAM_LABELS = {
    "db_operation_duration_seconds_bucket": frozenset({"operation", "le"}),
    "db_operation_duration_seconds_count": frozenset({"operation"}),
    "db_operation_duration_seconds_sum": frozenset({"operation"}),
}


def _prometheus_scrape(value: PrometheusSnapshotValue) -> PrometheusScrape:
    if isinstance(value, str):
        return PrometheusScrape(status="COLLECTED", text=value, reason=None)
    return value


def _validate_prometheus_sample(
    *,
    metric_name: str,
    labels: tuple[tuple[str, str], ...],
) -> None:
    label_map = dict(labels)
    if metric_name == "redis_publish_failures_total":
        if label_map:
            raise CollectorParseError("invalid labels for Prometheus target metric")
        return
    expected_labels = _DB_HISTOGRAM_LABELS.get(metric_name)
    if expected_labels is None:
        return
    if frozenset(label_map) != expected_labels:
        raise CollectorParseError("invalid labels for Prometheus target metric")
    if label_map["operation"] not in _DB_OPERATIONS:
        raise CollectorParseError("invalid operation for Prometheus target metric")


def parse_prometheus_samples(text: str) -> dict[PrometheusSampleKey, float]:
    samples: dict[PrometheusSampleKey, float] = {}
    try:
        for family in text_string_to_metric_families(text):
            for sample in family.samples:
                labels = tuple(
                    sorted((str(key), str(value)) for key, value in sample.labels.items())
                )
                sample_key = (sample.name, labels)
                if sample_key in samples:
                    raise CollectorParseError("duplicate Prometheus sample")
                _validate_prometheus_sample(
                    metric_name=sample.name,
                    labels=labels,
                )
                sample_value = float(sample.value)
                if not math.isfinite(sample_value):
                    raise CollectorParseError("non-finite Prometheus sample")
                samples[sample_key] = sample_value
    except CollectorParseError:
        raise
    except (TypeError, ValueError) as error:
        raise CollectorParseError("invalid Prometheus exposition format") from error
    return samples


def _missing_prometheus_metric(*, source: str, required: bool) -> dict[str, Any]:
    requirement = "required" if required else "optional"
    return {
        "status": "UNKNOWN",
        "evidence": "UNKNOWN",
        "observation": "MISSING",
        "value": None,
        "reason": f"{requirement} metric was absent from a successful Prometheus scrape",
        "source": source,
        "sample_count": 0,
    }


def _failed_prometheus_metric(
    *,
    source: str,
    required: bool,
    reason: str,
) -> dict[str, Any]:
    status = "FAILED" if required else "UNKNOWN"
    return {
        "status": status,
        "evidence": status,
        "observation": "COLLECTION_FAILED",
        "value": None,
        "reason": reason,
        "source": source,
        "sample_count": 0,
    }


def _operation_uses_source(*, operation: str, source: str) -> bool:
    service = source.partition("-")[0]
    return service == ("reaper" if operation == "reaper" else "worker")


def summarize_prometheus_deltas(
    *,
    before: Mapping[str, PrometheusSnapshotValue],
    after: Mapping[str, PrometheusSnapshotValue],
) -> dict[str, Any]:
    if set(before) != set(after):
        raise CollectorParseError("Prometheus before/after container identities do not match")
    operation_totals: dict[str, dict[str, Any]] = {}
    operation_sources: dict[str, set[str]] = {}
    missing_operation_sources: dict[str, set[str]] = {}
    redis_delta = 0.0
    redis_observed = False
    redis_sources: set[str] = set()
    redis_sample_count = 0
    missing_redis_sources: set[str] = set()
    collection_failures: dict[str, str] = {}
    for container in sorted(before):
        before_scrape = _prometheus_scrape(before[container])
        after_scrape = _prometheus_scrape(after[container])
        if (
            before_scrape.status == "COLLECTION_FAILED"
            or after_scrape.status == "COLLECTION_FAILED"
        ):
            collection_failures[container] = (
                before_scrape.reason or after_scrape.reason or "collection_failed"
            )
            continue
        if before_scrape.text is None or after_scrape.text is None:
            collection_failures[container] = "scrape_payload_missing"
            continue
        try:
            before_samples = parse_prometheus_samples(before_scrape.text)
            after_samples = parse_prometheus_samples(after_scrape.text)
        except CollectorParseError:
            collection_failures[container] = "scrape_parse_failed"
            continue
        keys = set(before_samples) | set(after_samples)
        for key in keys:
            metric_name, labels = key
            is_db_histogram = metric_name in _DB_HISTOGRAM_LABELS
            is_redis_counter = metric_name == "redis_publish_failures_total"
            if not is_db_histogram and not is_redis_counter:
                continue
            if key not in before_samples or key not in after_samples:
                if is_redis_counter:
                    missing_redis_sources.add(container)
                else:
                    missing_operation = dict(labels)["operation"]
                    missing_operation_sources.setdefault(missing_operation, set()).add(container)
                continue
            delta = after_samples[key] - before_samples[key]
            if delta < 0:
                raise CollectorParseError(f"Prometheus cumulative sample decreased for {container}")
            label_map = dict(labels)
            if metric_name == "redis_publish_failures_total":
                redis_observed = True
                redis_sources.add(container)
                redis_sample_count += 1
                redis_delta += delta
            elif is_db_histogram:
                operation_label = label_map["operation"]
                operation_sources.setdefault(operation_label, set()).add(container)
                aggregate = operation_totals.setdefault(
                    operation_label,
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
    db_operations: dict[str, dict[str, Any]] = {}
    for operation in _DB_OPERATIONS:
        expected_sources = {
            source
            for source in before
            if _operation_uses_source(operation=operation, source=source)
        }
        failed_sources = [
            source
            for source in collection_failures
            if _operation_uses_source(operation=operation, source=source)
        ]
        if failed_sources:
            db_operations[operation] = _failed_prometheus_metric(
                source=f'prometheus:db_operation_duration_seconds{{operation="{operation}"}}',
                required=operation in _REQUIRED_DB_OPERATIONS,
                reason=f"Prometheus collection failed for: {', '.join(failed_sources)}",
            )
            continue
        unobserved_sources = expected_sources - operation_sources.get(operation, set())
        if missing_operation_sources.get(operation) or unobserved_sources:
            db_operations[operation] = _missing_prometheus_metric(
                source=f'prometheus:db_operation_duration_seconds{{operation="{operation}"}}',
                required=operation in _REQUIRED_DB_OPERATIONS,
            )
            continue
        operation_aggregate = operation_totals.get(operation)
        if operation_aggregate is None:
            db_operations[operation] = _missing_prometheus_metric(
                source=f'prometheus:db_operation_duration_seconds{{operation="{operation}"}}',
                required=operation in _REQUIRED_DB_OPERATIONS,
            )
            continue
        count = float(operation_aggregate["count"])
        sum_seconds = float(operation_aggregate["sum_seconds"])
        db_operations[operation] = {
            "status": "VERIFIED",
            "evidence": "DIRECTIONAL" if count > 0 else "VERIFIED",
            "observation": "OBSERVED_VALUE" if count > 0 else "OBSERVED_ZERO",
            "value": count,
            "reason": "histogram was present in paired Prometheus scrapes",
            "source": f'prometheus:db_operation_duration_seconds{{operation="{operation}"}}',
            "sample_count": len(operation_sources[operation]),
            "count": count,
            "sum_seconds": sum_seconds,
            "mean_ms": sum_seconds * 1000 / count if count > 0 else None,
            "buckets": operation_aggregate["buckets"],
        }
    if collection_failures:
        redis_result = _failed_prometheus_metric(
            source="prometheus:redis_publish_failures_total",
            required=True,
            reason="Prometheus collection failed for: " + ", ".join(sorted(collection_failures)),
        )
    elif missing_redis_sources or set(before) - redis_sources or not redis_observed:
        redis_result = _missing_prometheus_metric(
            source="prometheus:redis_publish_failures_total",
            required=True,
        )
    else:
        redis_result = {
            "status": "VERIFIED",
            "evidence": "VERIFIED",
            "observation": "OBSERVED_ZERO" if redis_delta == 0 else "OBSERVED_VALUE",
            "value": redis_delta,
            "reason": "metric was present in paired Prometheus scrapes",
            "source": "prometheus:redis_publish_failures_total",
            "sample_count": redis_sample_count,
            "delta": redis_delta,
        }
    required_metrics_complete = (
        all(
            db_operations[operation]["status"] == "VERIFIED"
            for operation in _REQUIRED_DB_OPERATIONS
        )
        and redis_result["status"] == "VERIFIED"
    )
    return {
        "schema_version": PROMETHEUS_EVIDENCE_SCHEMA_VERSION,
        "required_metrics_complete": required_metrics_complete,
        "collection_failures": [
            {"source": source, "reason": reason}
            for source, reason in sorted(collection_failures.items())
        ],
        "db_operations": db_operations,
        "redis_publish_failures": redis_result,
    }
