import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from uuid import uuid4

import pytest


def test_missing_api_key_fails_without_contacting_server() -> None:
    environment = dict(os.environ)
    environment.pop("EVALOPS_TEST_MISSING_KEY", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.product_experiment_client",
            "--api-url",
            "http://127.0.0.1:1",
            "--api-key-env",
            "EVALOPS_TEST_MISSING_KEY",
            "get",
            str(uuid4()),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 2
    assert result.stderr.strip() == "api_key_environment_missing"
    assert not result.stdout


def test_submit_rejects_oversized_request_before_network(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_bytes(b" " * (1024 * 1024 + 1))
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_bytes(b"[]")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.product_experiment_client",
            "--api-url",
            "http://127.0.0.1:1",
            "--api-key-env",
            "EVALOPS_TEST_KEY",
            "submit",
            "--request",
            str(request_path),
            "--dataset",
            str(dataset_path),
            "--idempotency-key",
            "stable-key",
        ],
        env={**os.environ, "EVALOPS_TEST_KEY": "test-private-key"},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 2
    assert result.stderr.strip() == "invalid_client_configuration"
    assert not result.stdout


@pytest.mark.parametrize("operation", ["get", "cancel", "wait"])
def test_cli_controls_experiment_over_real_loopback_http(operation: str) -> None:
    experiment_id = uuid4()
    requests: list[tuple[str, str, str | None]] = []
    run = {
        "id": str(uuid4()),
        "dataset_version_id": str(uuid4()),
        "status": "succeeded",
        "total_jobs": 2,
        "succeeded_jobs": 2,
        "failed_jobs": 0,
        "cancelled_jobs": 0,
        "created_at": "2026-09-07T00:00:00Z",
        "started_at": "2026-09-07T00:00:00Z",
        "finished_at": "2026-09-07T00:00:01Z",
    }
    payload = json.dumps(
        {
            "id": str(experiment_id),
            "state": "READY_FOR_ASSESSMENT",
            "cancel_requested": False,
            "baseline": run,
            "candidate": {**run, "id": str(uuid4())},
        }
    ).encode()

    class Handler(BaseHTTPRequestHandler):
        def respond(self) -> None:
            requests.append((self.command, self.path, self.headers.get("Authorization")))
            self.send_response(202 if self.command == "POST" else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = respond
        do_POST = respond

        def log_message(self, format: str, *args: object) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.product_experiment_client",
                    "--api-url",
                    f"http://127.0.0.1:{server.server_port}",
                    "--api-key-env",
                    "EVALOPS_TEST_KEY",
                    operation,
                    str(experiment_id),
                ],
                env={**os.environ, "EVALOPS_TEST_KEY": "test-private-key"},
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["id"] == str(experiment_id)
    assert "test-private-key" not in result.stdout + result.stderr
    suffix = "/cancel" if operation == "cancel" else ""
    assert requests == [
        (
            "POST" if operation == "cancel" else "GET",
            f"/api/v1/experiments/{experiment_id}{suffix}",
            "Bearer test-private-key",
        )
    ]
