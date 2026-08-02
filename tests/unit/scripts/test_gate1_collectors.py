import json
import subprocess
from pathlib import Path

import pytest

import scripts.gate1_collectors as gate1_collectors
from scripts.gate1_collectors import (
    CollectorParseError,
    JsonlEvidenceWriter,
    PrometheusScrape,
    collect_docker_stats_snapshot,
    collect_prometheus_snapshot,
    parse_docker_stats,
    parse_prometheus_samples,
    summarize_prometheus_deltas,
    write_prometheus_snapshot,
)


def test_docker_stats_parser_preserves_raw_values_and_normalizes_resources() -> None:
    sample = parse_docker_stats(
        '{"Container":"worker-1","ID":"abc123","Name":"worker-1",'
        '"CPUPerc":"12.50%","MemUsage":"64.5MiB / 2GiB","MemPerc":"3.15%"}'
    )

    assert sample == {
        "container_id": "abc123",
        "container": "worker-1",
        "cpu_percent": 12.5,
        "rss_bytes": 67_633_152,
        "memory_limit_bytes": 2_147_483_648,
        "raw": {
            "cpu_percent": "12.50%",
            "memory_usage": "64.5MiB / 2GiB",
            "memory_percent": "3.15%",
        },
    }


def test_docker_stats_snapshot_binds_compose_service_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gate1_collectors,
        "collect_compose_service_rows",
        lambda **_: [
            {"ID": "worker-id", "Name": "project-worker-1", "Service": "worker"},
            {"ID": "api-id", "Name": "project-api-1", "Service": "api"},
        ],
    )

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        assert command == [
            "docker",
            "stats",
            "--no-stream",
            "--no-trunc",
            "--format",
            "{{json .}}",
            "worker-id",
            "api-id",
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '{"Container":"worker-id","ID":"worker-id","Name":"project-worker-1",'
                '"CPUPerc":"20.0%","MemUsage":"100MiB / 512MiB","MemPerc":"19.5%"}\n'
                '{"Container":"api-id","ID":"api-id","Name":"project-api-1",'
                '"CPUPerc":"5.0%","MemUsage":"80MiB / 512MiB","MemPerc":"15.6%"}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr(gate1_collectors.subprocess, "run", fake_run)

    samples = collect_docker_stats_snapshot(compose_file=tmp_path / "compose.yaml")

    assert [(sample["container"], sample["service"]) for sample in samples] == [
        ("project-worker-1", "worker"),
        ("project-api-1", "api"),
    ]


def test_docker_stats_parser_rejects_unknown_memory_unit() -> None:
    with pytest.raises(CollectorParseError, match="memory size"):
        parse_docker_stats(
            '{"Container":"worker-1","ID":"abc123","Name":"worker-1",'
            '"CPUPerc":"1.0%","MemUsage":"10frobs / 2GiB","MemPerc":"1.0%"}'
        )


def test_jsonl_evidence_writer_flushes_samples_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "raw" / "resources.jsonl"

    with JsonlEvidenceWriter(evidence_path) as writer:
        writer.append({"sample": 1})
        assert evidence_path.read_text(encoding="utf-8") == '{"sample":1}\n'

    with pytest.raises(FileExistsError):
        JsonlEvidenceWriter(evidence_path)


def test_prometheus_parser_keeps_histogram_operation_labels() -> None:
    samples = parse_prometheus_samples(
        """
# TYPE db_operation_duration_seconds histogram
db_operation_duration_seconds_bucket{operation="claim",le="0.01"} 3
db_operation_duration_seconds_count{operation="claim"} 4
db_operation_duration_seconds_sum{operation="claim"} 0.08
# TYPE redis_publish_failures_total counter
redis_publish_failures_total 2
"""
    )

    assert (
        samples[
            (
                "db_operation_duration_seconds_bucket",
                (("le", "0.01"), ("operation", "claim")),
            )
        ]
        == 3.0
    )
    assert (
        samples[
            (
                "db_operation_duration_seconds_count",
                (("operation", "claim"),),
            )
        ]
        == 4.0
    )
    assert samples[("redis_publish_failures_total", ())] == 2.0


def test_prometheus_delta_uses_same_container_before_and_after() -> None:
    before = {
        "worker-abc": """
db_operation_duration_seconds_bucket{operation="claim",le="0.01"} 1
db_operation_duration_seconds_count{operation="claim"} 1
db_operation_duration_seconds_sum{operation="claim"} 0.01
redis_publish_failures_total 2
"""
    }
    after = {
        "worker-abc": """
db_operation_duration_seconds_bucket{operation="claim",le="0.01"} 2
db_operation_duration_seconds_count{operation="claim"} 3
db_operation_duration_seconds_sum{operation="claim"} 0.05
redis_publish_failures_total 3
"""
    }

    delta = summarize_prometheus_deltas(before=before, after=after)

    assert delta["db_operations"]["claim"] == {
        "status": "VERIFIED",
        "evidence": "DIRECTIONAL",
        "observation": "OBSERVED_VALUE",
        "value": 2.0,
        "reason": "histogram was present in paired Prometheus scrapes",
        "source": 'prometheus:db_operation_duration_seconds{operation="claim"}',
        "sample_count": 1,
        "count": 2.0,
        "sum_seconds": 0.04,
        "mean_ms": 20.0,
        "buckets": {"0.01": 1.0},
    }
    assert delta["redis_publish_failures"] == {
        "status": "VERIFIED",
        "evidence": "VERIFIED",
        "observation": "OBSERVED_VALUE",
        "value": 1.0,
        "reason": "metric was present in paired Prometheus scrapes",
        "source": "prometheus:redis_publish_failures_total",
        "sample_count": 1,
        "delta": 1.0,
    }


def test_empty_prometheus_scrape_marks_metrics_missing_instead_of_verified_zero() -> None:
    delta = summarize_prometheus_deltas(
        before={"worker-abc": ""},
        after={"worker-abc": ""},
    )

    assert delta["schema_version"] == 2
    assert delta["required_metrics_complete"] is False
    assert delta["db_operations"]["claim"]["status"] == "UNKNOWN"
    assert delta["db_operations"]["claim"]["observation"] == "MISSING"
    assert delta["db_operations"]["claim"]["value"] is None
    assert delta["redis_publish_failures"]["status"] == "UNKNOWN"
    assert delta["redis_publish_failures"]["observation"] == "MISSING"
    assert delta["redis_publish_failures"]["value"] is None


def test_successful_scrape_without_target_metric_reports_missing() -> None:
    unrelated_metric = "process_cpu_seconds_total 1\n"

    delta = summarize_prometheus_deltas(
        before={"worker-abc": unrelated_metric},
        after={"worker-abc": unrelated_metric},
    )

    claim = delta["db_operations"]["claim"]
    failure = delta["db_operations"]["failure"]
    assert (claim["status"], claim["observation"], claim["value"]) == (
        "UNKNOWN",
        "MISSING",
        None,
    )
    assert "required metric" in claim["reason"]
    assert (failure["status"], failure["observation"], failure["value"]) == (
        "UNKNOWN",
        "MISSING",
        None,
    )
    assert "optional metric" in failure["reason"]


def test_observed_zero_prometheus_delta_is_verified_zero() -> None:
    delta = summarize_prometheus_deltas(
        before={"worker-abc": "redis_publish_failures_total 2\n"},
        after={"worker-abc": "redis_publish_failures_total 2\n"},
    )

    redis = delta["redis_publish_failures"]
    assert redis["status"] == "VERIFIED"
    assert redis["observation"] == "OBSERVED_ZERO"
    assert redis["value"] == 0.0
    assert redis["sample_count"] == 1


def test_invalid_prometheus_format_is_a_collection_failure() -> None:
    delta = summarize_prometheus_deltas(
        before={"worker-abc": "redis_publish_failures_total 0\n"},
        after={"worker-abc": "redis_publish_failures_total not-a-number\n"},
    )

    assert delta["required_metrics_complete"] is False
    claim = delta["db_operations"]["claim"]
    assert (claim["status"], claim["observation"], claim["value"]) == (
        "FAILED",
        "COLLECTION_FAILED",
        None,
    )
    redis = delta["redis_publish_failures"]
    assert (redis["status"], redis["observation"], redis["value"]) == (
        "FAILED",
        "COLLECTION_FAILED",
        None,
    )
    optional_failure = delta["db_operations"]["failure"]
    assert (
        optional_failure["status"],
        optional_failure["observation"],
        optional_failure["value"],
    ) == ("UNKNOWN", "COLLECTION_FAILED", None)


def test_prometheus_endpoint_failure_remains_collection_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_docker_run(
        command: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        if "compose" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout='[{"Service":"worker","ID":"abcdef1234567890"}]',
                stderr="",
            )
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(subprocess, "run", fake_docker_run)

    snapshot = collect_prometheus_snapshot(compose_file=Path("deploy/compose.yaml"))

    scrape = snapshot["worker-abcdef123456"]
    assert scrape.status == "COLLECTION_FAILED"
    assert scrape.text is None
    assert scrape.reason == "endpoint_request_failed"
    delta = summarize_prometheus_deltas(before=snapshot, after=snapshot)
    assert delta["db_operations"]["claim"]["status"] == "FAILED"
    assert delta["db_operations"]["claim"]["observation"] == "COLLECTION_FAILED"
    assert delta["db_operations"]["claim"]["value"] is None


def test_prometheus_snapshot_writer_preserves_collection_failure_reason(
    tmp_path: Path,
) -> None:
    write_prometheus_snapshot(
        directory=tmp_path,
        phase="before",
        snapshots={
            "worker-ok": PrometheusScrape(
                status="COLLECTED",
                text="redis_publish_failures_total 0\n",
                reason=None,
            ),
            "worker-failed": PrometheusScrape(
                status="COLLECTION_FAILED",
                text=None,
                reason="endpoint_request_failed",
            ),
        },
    )

    phase_directory = tmp_path / "prometheus" / "before"
    assert (phase_directory / "worker-ok.prom").read_text(
        encoding="utf-8"
    ) == "redis_publish_failures_total 0\n"
    assert json.loads(
        (phase_directory / "collection_failures.json").read_text(encoding="utf-8")
    ) == {"worker-failed": "endpoint_request_failed"}
    assert not (phase_directory / "worker-failed.prom").exists()


def test_duplicate_prometheus_sample_is_a_collection_failure() -> None:
    duplicate = "redis_publish_failures_total 0\nredis_publish_failures_total 0\n"

    delta = summarize_prometheus_deltas(
        before={"worker-abc": duplicate},
        after={"worker-abc": duplicate},
    )

    redis = delta["redis_publish_failures"]
    assert (redis["status"], redis["observation"], redis["value"]) == (
        "FAILED",
        "COLLECTION_FAILED",
        None,
    )


def test_prometheus_target_with_unexpected_labels_is_a_collection_failure() -> None:
    invalid_labels = """
db_operation_duration_seconds_count{operation="claim",tenant="tenant-a"} 1
db_operation_duration_seconds_sum{operation="claim",tenant="tenant-a"} 0.01
redis_publish_failures_total 0
"""

    delta = summarize_prometheus_deltas(
        before={"worker-abc": invalid_labels},
        after={"worker-abc": invalid_labels},
    )

    claim = delta["db_operations"]["claim"]
    assert (claim["status"], claim["observation"], claim["value"]) == (
        "FAILED",
        "COLLECTION_FAILED",
        None,
    )


@pytest.mark.parametrize("non_finite", ["NaN", "+Inf", "-Inf"])
def test_non_finite_prometheus_sample_is_a_collection_failure(non_finite: str) -> None:
    delta = summarize_prometheus_deltas(
        before={"worker-abc": "redis_publish_failures_total 0\n"},
        after={"worker-abc": f"redis_publish_failures_total {non_finite}\n"},
    )

    redis = delta["redis_publish_failures"]
    assert (redis["status"], redis["observation"], redis["value"]) == (
        "FAILED",
        "COLLECTION_FAILED",
        None,
    )


def test_metric_missing_from_one_paired_scrape_is_missing() -> None:
    delta = summarize_prometheus_deltas(
        before={"worker-abc": "process_cpu_seconds_total 1\n"},
        after={"worker-abc": "redis_publish_failures_total 1\n"},
    )

    redis = delta["redis_publish_failures"]
    assert (redis["status"], redis["observation"], redis["value"]) == (
        "UNKNOWN",
        "MISSING",
        None,
    )
    assert delta["required_metrics_complete"] is False


def test_required_metric_missing_from_one_worker_invalidates_comparison() -> None:
    worker_with_claim = """
db_operation_duration_seconds_count{operation="claim"} 1
db_operation_duration_seconds_sum{operation="claim"} 0.01
db_operation_duration_seconds_bucket{operation="claim",le="+Inf"} 1
redis_publish_failures_total 0
"""
    worker_without_claim = "redis_publish_failures_total 0\n"

    delta = summarize_prometheus_deltas(
        before={
            "worker-a": worker_with_claim,
            "worker-b": worker_without_claim,
        },
        after={
            "worker-a": worker_with_claim,
            "worker-b": worker_without_claim,
        },
    )

    claim = delta["db_operations"]["claim"]
    assert (claim["status"], claim["observation"], claim["value"]) == (
        "UNKNOWN",
        "MISSING",
        None,
    )
    assert delta["required_metrics_complete"] is False


def test_optional_metric_missing_stays_unknown_without_invalidating_required_metrics() -> None:
    required_metrics = """
db_operation_duration_seconds_count{operation="claim"} 1
db_operation_duration_seconds_sum{operation="claim"} 0.01
db_operation_duration_seconds_bucket{operation="claim",le="+Inf"} 1
db_operation_duration_seconds_count{operation="result"} 1
db_operation_duration_seconds_sum{operation="result"} 0.02
db_operation_duration_seconds_bucket{operation="result",le="+Inf"} 1
redis_publish_failures_total 0
"""

    delta = summarize_prometheus_deltas(
        before={"worker-abc": required_metrics},
        after={"worker-abc": required_metrics},
    )

    failure = delta["db_operations"]["failure"]
    assert (failure["status"], failure["observation"], failure["value"]) == (
        "UNKNOWN",
        "MISSING",
        None,
    )
    assert delta["db_operations"]["claim"]["observation"] == "OBSERVED_ZERO"
    assert delta["db_operations"]["claim"]["value"] == 0.0
    assert delta["required_metrics_complete"] is True
