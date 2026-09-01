from pathlib import Path

import pytest

import scripts.verify_observability_stack as verifier


def test_verify_requires_four_targets_metrics_and_three_span_roles(monkeypatch) -> None:
    queries: list[str] = []

    def fake_json(url: str) -> dict[str, object]:
        queries.append(url)
        if url.endswith("/api/v1/targets"):
            return {
                "data": {
                    "activeTargets": [
                        {"scrapePool": f"evalops-{role}", "health": "up"}
                        for role in ("api", "worker", "reaper", "audit-dispatcher")
                    ]
                }
            }
        return {"data": {"result": [{"value": [1, "1"]}]}}

    monkeypatch.setattr(verifier, "_json", fake_json)
    monkeypatch.setattr(
        verifier,
        "_collector_logs",
        lambda _path: "Str(api) Str(worker) Str(reaper)",
    )

    verifier.verify(
        prometheus_url="http://prometheus",
        compose_file=Path("deploy/compose.yaml"),
        deadline_seconds=1,
    )

    assert len(queries) == 9
    assert any("api_request_total" in query for query in queries)
    assert any("job_retry_total" in query for query in queries)
    assert any("mcp_audit_pending" in query for query in queries)
    assert any("mcp_audit_dead_letter_count" in query for query in queries)
    assert any("mcp_audit_delivery_latency_seconds_count" in query for query in queries)


def test_metric_query_fails_closed_when_series_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(verifier, "_json", lambda _url: {"data": {"result": []}})

    with pytest.raises(RuntimeError, match="no series"):
        verifier._require_metric("http://prometheus", "job_queue_depth")


def test_target_wait_fails_closed_after_deadline() -> None:
    with pytest.raises(RuntimeError, match="did not become healthy"):
        verifier._wait_for_prometheus("http://prometheus", 0)
