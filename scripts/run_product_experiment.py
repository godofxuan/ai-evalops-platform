"""Run a declarative paired experiment and emit portable evidence and HTML."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from app.product_experiments.report import render_experiment_html
from app.product_experiments.runner import ProductExperimentResult, run_experiment


def _git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write(path: Path, payload: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": path.name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "byte_size": len(payload),
    }


def write_product_artifacts(
    result: ProductExperimentResult,
    *,
    output_dir: Path,
    command: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    result_values = result.model_dump(mode="json")
    entries = [
        _write(output_dir / "result.json", _json_bytes(result_values)),
        _write(
            output_dir / "report.html",
            render_experiment_html(result_values).encode("utf-8"),
        ),
    ]
    for label in ("baseline", "candidate"):
        arm = result.arms.get(label)
        if arm is not None:
            entries.append(
                _write(
                    output_dir / f"{label}.json",
                    _json_bytes(arm.model_dump(mode="json")),
                )
            )
    manifest = {
        "schema_version": "evalops.product-experiment-manifest/1.0",
        "experiment_id": result.experiment_id,
        "status": result.status,
        "task_type": result.task_type,
        "dataset_sha256": result.dataset_sha256,
        "evalops_sha": result.evalops_sha,
        "source_identities": result.source_identities,
        "producing_command": command,
        "files": entries,
        "formal_quality_claim_allowed": False,
        "agent_tool_use_assessment": result.agent_tool_use_assessment,
        "human_review_status": "PENDING",
        "production_ready": False,
    }
    manifest_entry = _write(output_dir / "manifest.json", _json_bytes(manifest))
    return {**manifest, "manifest_file": manifest_entry}


async def _run(args: argparse.Namespace) -> int:
    evalops_sha = args.evalops_sha or _git_sha()
    result = await run_experiment(args.spec, evalops_sha=evalops_sha)
    command = f"python -m scripts.run_product_experiment --spec {args.spec}"
    write_product_artifacts(result, output_dir=args.output_dir, command=command)
    print(
        f"experiment={result.experiment_id} status={result.status} "
        f"cases={result.case_count} report={args.output_dir / 'report.html'}"
    )
    return 2 if result.status in {"INPUT_REQUIRED", "INSUFFICIENT_EVIDENCE"} else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/product-experiment"))
    parser.add_argument("--evalops-sha")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
