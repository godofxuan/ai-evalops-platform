import asyncio
import hashlib
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from app.product_experiments.durable_bundle import verify_durable_bundle, write_durable_bundle
from app.product_experiments.durable_report import build_durable_report
from app.product_experiments.export_service import encode_report
from tests.unit.product_experiments.test_durable_report import durable_evidence as durable_evidence
from tests.unit.product_experiments.test_submission import submission_inputs as submission_inputs


async def test_private_bundle_can_be_recomputed_and_never_overwrites_output(
    durable_evidence, tmp_path: Path
):
    snapshot, raw = durable_evidence
    payload = encode_report(build_durable_report(snapshot=snapshot, raw_dataset=raw))
    output = tmp_path / "evidence"
    verification = write_durable_bundle(payload, output_dir=output, raw_dataset=raw)
    assert verification.verification_scope == "PRIVATE_RECOMPUTED"
    assert verify_durable_bundle(output) == verification
    assert (output / "report.json").read_bytes() == payload
    assert (output / "dataset.json").read_bytes() == raw
    with pytest.raises(ValueError, match="output_already_exists"):
        write_durable_bundle(payload, output_dir=output, raw_dataset=raw)
    assert (output / "report.json").read_bytes() == payload
    (output / "report.html").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError):
        verify_durable_bundle(output)
    manifest = json.loads((output / "manifest.json").read_bytes())
    manifest["files"]["report.html"] = {
        "sha256": hashlib.sha256(b"tampered").hexdigest(),
        "byte_size": len(b"tampered"),
    }
    (output / "manifest.json").write_bytes(encode_report(manifest))
    with pytest.raises(ValueError, match="bundle_html_mismatch"):
        verify_durable_bundle(output)


async def test_cli_verifies_bundle_offline_without_api_credentials(
    durable_evidence, tmp_path: Path
):
    snapshot, raw = durable_evidence
    output = tmp_path / "offline-evidence"
    payload = encode_report(build_durable_report(snapshot=snapshot, raw_dataset=raw))
    write_durable_bundle(payload, output_dir=output, raw_dataset=raw)
    process = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "scripts.product_experiment_client", "verify", str(output)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    summary = json.loads(process.stdout)
    assert summary["verification_scope"] == "PRIVATE_RECOMPUTED"
    assert summary["quality_status"] == "INSUFFICIENT_EVIDENCE"
    assert summary["formal_quality_claim_allowed"] is False


async def test_private_export_preserves_quality_exit_and_reproducible_bundle(
    durable_evidence, tmp_path: Path
):
    snapshot, raw = durable_evidence
    payload = encode_report(build_durable_report(snapshot=snapshot, raw_dataset=raw))
    raw_path = tmp_path / "source.json"
    raw_path.write_bytes(raw)
    output = tmp_path / "exported"
    paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            paths.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            process = await asyncio.to_thread(
                subprocess.run,
                [
                    sys.executable,
                    "-m",
                    "scripts.product_experiment_client",
                    "--api-url",
                    f"http://127.0.0.1:{server.server_port}",
                    "--api-key-env",
                    "EVALOPS_TEST_KEY",
                    "export",
                    snapshot["experiment_id"],
                    "--include-private",
                    "--dataset",
                    str(raw_path),
                    "--output-dir",
                    str(output),
                ],
                env={**os.environ, "EVALOPS_TEST_KEY": "test-key"},
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        finally:
            await asyncio.to_thread(server.shutdown)
            thread.join(timeout=5)
    assert process.returncode == 2, process.stderr
    assert json.loads(process.stdout)["verification_scope"] == "PRIVATE_RECOMPUTED"
    assert verify_durable_bundle(output).quality_status == "INSUFFICIENT_EVIDENCE"
    assert paths == [f"/api/v1/experiments/{snapshot['experiment_id']}/export?include_private=true"]
