from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


def _json(url: str) -> dict[str, object]:
    with urlopen(url, timeout=3) as response:  # noqa: S310 - fixed operator URL
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("observability endpoint returned a non-object")
    return payload


def _wait_for_prometheus(base_url: str, deadline_seconds: float) -> None:
    deadline = time.monotonic() + deadline_seconds
    last_error = "not queried"
    while time.monotonic() < deadline:
        try:
            payload = _json(f"{base_url}/api/v1/targets")
            data = payload.get("data")
            active = data.get("activeTargets") if isinstance(data, dict) else None
            if not isinstance(active, list):
                raise RuntimeError("Prometheus target response is incomplete")
            states = {
                item.get("scrapePool"): item.get("health")
                for item in active
                if isinstance(item, dict)
            }
            expected = {
                "evalops-api",
                "evalops-worker",
                "evalops-reaper",
                "evalops-audit-dispatcher",
            }
            if states.keys() >= expected and all(states[name] == "up" for name in expected):
                return
            last_error = f"target states: {states}"
        except Exception as error:
            last_error = type(error).__name__
        time.sleep(1)
    raise RuntimeError(f"Prometheus targets did not become healthy: {last_error}")


def _require_metric(base_url: str, expression: str) -> None:
    payload = _json(f"{base_url}/api/v1/query?{urlencode({'query': expression})}")
    data = payload.get("data")
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, list) or not result:
        raise RuntimeError(f"Prometheus query returned no series: {expression}")


def _collector_logs(compose_file: Path) -> str:
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "logs",
            "--no-color",
            "otel-collector",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError("failed to read OpenTelemetry Collector logs")
    return completed.stdout


def verify(*, prometheus_url: str, compose_file: Path, deadline_seconds: float) -> None:
    _wait_for_prometheus(prometheus_url, deadline_seconds)
    for metric in (
        "api_request_total",
        "db_operation_duration_seconds_count",
        "job_queue_depth",
        "job_retry_total",
        "job_lease_expired_total",
        "mcp_audit_pending",
        "mcp_audit_dead_letter_count",
    ):
        _require_metric(prometheus_url, metric)

    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        logs = _collector_logs(compose_file)
        if all(f"Str({role})" in logs for role in ("api", "worker", "reaper")):
            print("verified Prometheus targets/metrics and API/Worker/Reaper OTLP spans")
            return
        time.sleep(1)
    raise RuntimeError("Collector did not receive spans from API, Worker, and Reaper")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prometheus-url", default="http://127.0.0.1:9090")
    parser.add_argument("--compose-file", type=Path, default=Path("deploy/compose.yaml"))
    parser.add_argument("--deadline-seconds", type=float, default=60)
    args = parser.parse_args(argv)
    verify(
        prometheus_url=args.prometheus_url.rstrip("/"),
        compose_file=args.compose_file,
        deadline_seconds=args.deadline_seconds,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
