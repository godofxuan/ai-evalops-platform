"""Run a declarative paired experiment and emit portable evidence and HTML."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from app.product_experiments.public_summary import project_public_summary
from app.product_experiments.report import render_experiment_html
from app.product_experiments.runner import (
    DatasetIntegrityError,
    ProductExperimentResult,
    preflight_experiment,
    run_experiment,
)
from app.product_experiments.spec import InputLimitError
from app.targets.base import InvalidTargetConfiguration
from scripts.verify_product_experiment import verify_manifest


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
    export_mode: Literal["public", "private"] = "public",
) -> dict[str, Any]:
    if export_mode not in {"public", "private"}:
        raise ValueError("unsupported export mode")
    if output_dir.is_symlink() or (
        output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir()))
    ):
        raise FileExistsError("experiment output must be a new or empty non-symlink directory")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir.parent / f".{output_dir.name}.export.lock"
    lock = lock_path.open("x", encoding="utf-8")
    try:
        with tempfile.TemporaryDirectory(prefix=".evalops-export-", dir=output_dir.parent) as root:
            staging = Path(root) / "bundle"
            manifest = _write_product_artifacts(result, output_dir=staging, command=command)
            verify_manifest(staging / "manifest.json")
            if export_mode == "public":
                private_digest = hashlib.sha256((staging / "result.json").read_bytes()).hexdigest()
                staging = Path(root) / "public"
                summary = project_public_summary(result, private_result_sha256=private_digest)
                values = summary.model_dump(mode="json")
                entries = [
                    _write(staging / "result.json", _json_bytes(values)),
                    _write(staging / "report.html", render_experiment_html(values).encode("utf-8")),
                ]
                manifest = {
                    "schema_version": "evalops.public-experiment-manifest/1.0",
                    "export_mode": "public",
                    "experiment_id": summary.experiment_id,
                    "status": summary.status,
                    "private_result_sha256": private_digest,
                    "files": entries,
                    "formal_quality_claim_allowed": False,
                    "production_ready": False,
                }
                entry = _write(staging / "manifest.json", _json_bytes(manifest))
                verify_manifest(staging / "manifest.json")
                manifest = {**manifest, "manifest_file": entry}
            if output_dir.is_symlink():
                raise FileExistsError("output changed during export")
            if output_dir.exists():
                output_dir.rmdir()  # Only an empty directory can be removed.
            staging.rename(output_dir)
            return manifest
    finally:
        lock.close()
        lock_path.unlink()


def _write_product_artifacts(
    result: ProductExperimentResult, *, output_dir: Path, command: str
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
        "schema_version": "evalops.product-experiment-manifest/"
        + result.schema_version.rsplit("/", 1)[1],
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
    if args.validate_only:
        preflight = preflight_experiment(args.spec)
        print(json.dumps(preflight, ensure_ascii=False, sort_keys=True))
        return 0 if preflight["status"] == "READY" and args.gate == "automated" else 2
    evalops_sha = args.evalops_sha or _git_sha()
    result = await run_experiment(args.spec, evalops_sha=evalops_sha)
    command = f"python -m scripts.run_product_experiment --spec {args.spec}"
    write_product_artifacts(
        result, output_dir=args.output_dir, command=command, export_mode=args.export_mode
    )
    print(
        f"experiment={result.experiment_id} status={result.status} "
        f"cases={result.case_count} report={args.output_dir / 'report.html'}"
    )
    return experiment_exit_code(result.status, gate=args.gate)


def experiment_exit_code(status: str, *, gate: str) -> int:
    if gate not in {"automated", "formal"}:
        return 3
    if status in {"DEMO_FAIL", "AUTOMATED_FAIL"}:
        return 1
    if status in {"INPUT_REQUIRED", "INSUFFICIENT_EVIDENCE"}:
        return 2
    if status in {"DEMO_PASS", "AUTOMATED_PASS_HUMAN_REVIEW_PENDING"}:
        return 2 if gate == "formal" else 0
    return 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/product-experiment"))
    parser.add_argument("--evalops-sha")
    parser.add_argument(
        "--export-mode",
        choices=("public", "private"),
        default="public",
        help="Public summary by default; private includes prompts, answers and tool payloads.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate inputs without calling targets or writing execution artifacts.",
    )
    parser.add_argument(
        "--gate",
        choices=("automated", "formal"),
        default="automated",
        help="Formal gate stays blocked while formal quality approval is unavailable.",
    )
    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print(json.dumps({"error_code": "experiment_interrupted"}), file=sys.stderr)
        return 130
    except (
        ValidationError,
        DatasetIntegrityError,
        InvalidTargetConfiguration,
        InputLimitError,
        FileNotFoundError,
    ):
        print(json.dumps({"error_code": "experiment_input_invalid"}), file=sys.stderr)
        return 2
    except Exception:
        # This is the CLI boundary only; library callers still receive the original exception.
        print(json.dumps({"error_code": "experiment_execution_or_export_failed"}), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
