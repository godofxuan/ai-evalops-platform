from pathlib import Path

import pytest

from scripts.gate1_collectors import (
    CollectorParseError,
    JsonlEvidenceWriter,
    parse_docker_stats,
    parse_prometheus_samples,
    summarize_prometheus_deltas,
)


def test_docker_stats_parser_preserves_raw_values_and_normalizes_resources() -> None:
    sample = parse_docker_stats(
        '{"Container":"worker-1","CPUPerc":"12.50%","MemUsage":"64.5MiB / 2GiB","MemPerc":"3.15%"}'
    )

    assert sample == {
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


def test_docker_stats_parser_rejects_unknown_memory_unit() -> None:
    with pytest.raises(CollectorParseError, match="memory size"):
        parse_docker_stats(
            '{"Container":"worker-1","CPUPerc":"1.0%","MemUsage":"10frobs / 2GiB","MemPerc":"1.0%"}'
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
        "evidence": "DIRECTIONAL",
        "count": 2.0,
        "sum_seconds": 0.04,
        "mean_ms": 20.0,
        "buckets": {"0.01": 1.0},
    }
    assert delta["redis_publish_failures"] == {
        "evidence": "VERIFIED",
        "delta": 1.0,
    }
