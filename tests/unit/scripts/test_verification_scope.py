"""Local verification is a structural operation, never a claim of quality recomputation."""

import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from app.product_experiments.runner import run_experiment
from scripts.run_product_experiment import write_product_artifacts
from scripts.verify_product_experiment import verify_manifest

ROOT = Path(__file__).resolve().parents[3]


async def test_local_semantic_rehash_is_explicitly_structure_only(tmp_path):
    result = await run_experiment(
        ROOT / "benchmarks/product_demo_v1/experiment.json", evalops_sha="a" * 40
    )
    output = tmp_path / "local-private"
    write_product_artifacts(
        result, output_dir=output, command="synthetic-test", export_mode="private"
    )
    report = json.loads((output / "result.json").read_bytes())
    report["status"] = "DEMO_FAIL"
    raw = json.dumps(report).encode()
    (output / "result.json").write_bytes(raw)
    manifest = json.loads((output / "manifest.json").read_bytes())
    manifest["status"] = "DEMO_FAIL"
    for entry in manifest["files"]:
        if entry["path"] == "result.json":
            entry.update(sha256=hashlib.sha256(raw).hexdigest(), byte_size=len(raw))
    (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_manifest(output / "manifest.json")["status"] == "DEMO_FAIL"
    command = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "scripts.verify_product_experiment", str(output / "manifest.json")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert command.returncode == 0
    summary = json.loads(command.stdout)
    assert summary["verification_scope"] == "LOCAL_PRIVATE_STRUCTURE_ONLY"
    assert summary["reported_quality_status"] == "DEMO_FAIL"
    assert summary["quality_recomputed"] is False


def test_public_cli_is_projection_only():
    command = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.verify_product_experiment",
            str(ROOT / "docs/results/trustworthy_product_v2/qa/manifest.json"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert command.returncode == 0
    summary = json.loads(command.stdout)
    assert summary["verification_scope"] == "PUBLIC_PROJECTION_ONLY"
    assert summary["quality_recomputed"] is False
