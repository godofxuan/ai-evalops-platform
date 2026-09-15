"""One entry point: demo/run, explain, blind calibration, and full-set regression replay."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.core.strict_json import decode_evidence_json
from app.product_experiments.learning_bundle import (
    require_new_output,
    verify_learning_bundle,
    write_learning_bundle,
)
from app.product_experiments.learning_calibration_bundle import (
    calibration_files,
    verify_calibration_bundle,
)
from app.product_experiments.learning_grading import (
    MAX_REVIEW_ITEMS,
    grade_answer,
)
from app.product_experiments.learning_recovery import load_capture
from app.product_experiments.learning_workflow import (
    json_bytes,
    load_evidence,
    read_file,
)
from app.product_experiments.reliability_client import _lock as directory_lock
from app.product_experiments.runner import preflight_experiment, run_experiment
from app.product_experiments.spec import load_experiment_spec
from app.product_experiments.trace_diagnostics import parse_otlp_traces
from scripts.run_product_experiment import (
    _validated_sha,
    experiment_exit_code,
    write_product_artifacts,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("normalized_exact_v1", "json_structural_v1")


def _sha() -> str:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _publish_files(output: Path, files: dict[str, bytes]) -> None:
    with directory_lock(output):
        require_new_output(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".evalops-workflow-command-", dir=output.parent) as root:
            stage = Path(root) / "bundle"
            stage.mkdir()
            for name, payload in files.items():
                (stage / name).write_bytes(payload)
            require_new_output(output)
            stage.rename(output)


def initialize_demo(output: Path, *, task: str) -> None:
    name = "agent_tool_demo_v1" if task == "agent" else "product_demo_v1"
    loaded = load_experiment_spec(ROOT / "benchmarks" / name / "experiment.json")
    spec = loaded.spec.model_dump(mode="json")
    spec["dataset"]["path"] = "cases.json"
    spec["policy_path"] = "policy.json"
    _publish_files(
        output,
        {
            "experiment.json": json_bytes(spec),
            "cases.json": read_file(loaded.dataset_path, 10 * 1024 * 1024),
            "policy.json": read_file(loaded.policy_path, 1024 * 1024),
        },
    )


async def run_workflow(args: argparse.Namespace, spec: Path) -> int:
    from app.product_experiments.public_summary import project_public_summary
    from app.product_experiments.report import render_experiment_html
    from scripts.verify_product_experiment import verify_manifest

    # Validate output and all local inputs before any potentially paid target request.
    with directory_lock(args.output_dir):
        require_new_output(args.output_dir)
        code_sha = _validated_sha(args.evalops_sha or _sha())
        preflight = preflight_experiment(spec)
        if preflight["status"] != "READY":
            print(json_bytes(preflight).decode(), end="")
            return 2
        if args.include_private and preflight["planned_case_executions"] > MAX_REVIEW_ITEMS:
            print(
                '{"status":"INPUT_REQUIRED","error_code":"diagnostic_review_item_limit",'
                '"execution_status":"NOT_RUN"}'
            )
            return 2
        grade_answer("", "", profile=args.profile)
        traces = parse_otlp_traces(read_file(args.traces, 8 * 1024 * 1024)) if args.traces else None
        loaded = load_experiment_spec(spec)
        raw = read_file(loaded.dataset_path, 10 * 1024 * 1024)
        args.output_dir.parent.mkdir(parents=True, exist_ok=True)
        # Allocate before execution; retain this directory on every post-run failure.
        staging = TemporaryDirectory(
            prefix=".evalops-run-", dir=args.output_dir.parent, delete=False
        )
        stage = Path(staging.name)  # Python 3.12 TemporaryDirectory returns an absolute path.
        try:
            result = await run_experiment(spec, evalops_sha=code_sha)
        except BaseException:
            staging.cleanup()  # No returned execution evidence is available to capture.
            raise
        capture_complete = False
        output_published = False
        visibility = "PRIVATE" if args.include_private else "PUBLIC"
        try:
            result_bytes = json_bytes(result.model_dump(mode="json"))
            private_digest = hashlib.sha256(result_bytes).hexdigest()
            public = project_public_summary(result, private_result_sha256=private_digest)
            captures = (
                {"captured-result.json": result_bytes, "captured-dataset.json": raw}
                if args.include_private
                else {"captured-public-result.json": json_bytes(public.model_dump(mode="json"))}
            )
            for name, data in captures.items():
                (stage / name).write_bytes(data)
            if args.include_private and hashlib.sha256(raw).hexdigest() != result.dataset_sha256:
                raise ValueError("captured_dataset_identity_mismatch")
            capture_status = {
                "schema_version": "evalops.workflow-capture/1.0",
                "status": "CAPTURED_NOT_EXPORTED",
                "visibility": visibility,
                "original_quality_status": result.status,
                "files": {
                    name: {"sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data)}
                    for name, data in captures.items()
                },
                "verification_scope": "CAPTURE_ONLY_NOT_VERIFIED",
                "source_provenance_verified": False,
                "formal_quality_claim_allowed": False,
                "production_ready": False,
            }
            # Write the completion marker last; a partial capture is never marked complete.
            (stage / "capture-status.json").write_bytes(json_bytes(capture_status))
            capture_complete = True
            if args.include_private:
                write_product_artifacts(
                    result,
                    output_dir=stage / "source",
                    command="evaluation_workflow",
                    export_mode="private",
                )
                dataset = stage / "source" / "dataset.json"
                dataset.write_bytes(raw)
                evidence = load_evidence(stage / "source", dataset_path=dataset)
                try:
                    write_learning_bundle(
                        evidence, output_dir=stage / "output", profile=args.profile, traces=traces
                    )
                except (ValueError, OSError):
                    # The target has already run. Retain its immutable source instead of
                    # deleting it with the diagnostic staging directory or calling again.
                    recovery = stage / "recovery"
                    recovery.mkdir()
                    (stage / "source").rename(recovery / "source")
                    blocked = {
                        "status": "EXECUTED_ANALYSIS_BLOCKED",
                        "error_code": "diagnostic_export_failed",
                        "source_evidence": "source",
                        "visibility": "PRIVATE",
                        "retry": "OFFLINE_ANALYSIS_ONLY_NO_TARGET_RERUN",
                        "original_quality_status": result.status,
                        "formal_quality_claim_allowed": False,
                    }
                    (recovery / "status.json").write_bytes(json_bytes(blocked))
                    require_new_output(args.output_dir)
                    recovery.rename(args.output_dir)
                    output_published = True
                    staging.cleanup()
                    print(json_bytes(blocked).decode(), end="")
                    return 3
                verification = "DIAGNOSTICS_RECOMPUTED"
            else:
                # Build only the existing public allowlist: never stage raw observations
                # on disk in public mode, including during failed export cleanup.
                public_values = public.model_dump(mode="json")
                files = {
                    "result.json": json_bytes(public_values),
                    "report.html": render_experiment_html(public_values).encode("utf-8"),
                }
                manifest = {
                    "schema_version": "evalops.public-experiment-manifest/1.0",
                    "export_mode": "public",
                    "experiment_id": public.experiment_id,
                    "status": public.status,
                    "private_result_sha256": private_digest,
                    "files": [
                        {
                            "path": name,
                            "sha256": hashlib.sha256(data).hexdigest(),
                            "byte_size": len(data),
                        }
                        for name, data in files.items()
                    ],
                    "formal_quality_claim_allowed": False,
                    "production_ready": False,
                }
                _publish_files(stage / "output", {**files, "manifest.json": json_bytes(manifest)})
                verify_manifest(stage / "output" / "manifest.json")
                verification = "PUBLIC_PROJECTION_ONLY"
            require_new_output(args.output_dir)
            (stage / "output").rename(args.output_dir)
            output_published = True
            staging.cleanup()
        except BaseException:
            if capture_complete:
                try:
                    capture_complete = read_file(
                        stage / "capture-status.json", 1024 * 1024
                    ) == json_bytes(capture_status) and all(
                        read_file(stage / name, len(data)) == data
                        for name, data in captures.items()
                    )
                except (ValueError, OSError):
                    capture_complete = False
            blocked = {
                "schema_version": "evalops.workflow-export-status/1.0",
                "status": "EXECUTED_EXPORT_BLOCKED",
                "error_code": "post_execution_export_failed",
                "original_quality_status": result.status,
                "visibility": visibility,
                "capture_status": "COMPLETE" if capture_complete else "FAILED",
                "output_published": output_published,
                "recovery_path": str(stage),
                "retry": "OFFLINE_RECOVERY_ONLY_NO_TARGET_RERUN",
                "formal_quality_claim_allowed": False,
                "production_ready": False,
            }
            try:
                (stage / "export-status.json").write_bytes(json_bytes(blocked))
            except (ValueError, OSError):
                # Full/unwritable storage can prevent even the failure marker being saved.
                blocked["recovery_status_write"] = "FAILED"
            print(json_bytes(blocked).decode(), end="")
            return 3
        print(
            json_bytes(
                {
                    "status": result.status,
                    "verification_scope": verification,
                    "visibility": "PRIVATE" if args.include_private else "PUBLIC",
                    "report": str(args.output_dir / "report.html"),
                    "source_scope": "DEMO_FIXTURES"
                    if all(arm.provider.type == "fixture" for arm in loaded.spec.arms)
                    else "DECLARED_HTTP_TARGETS",
                    "code_pin_scope": "DECLARED_GIT_PIN_NOT_RELEASE_ATTESTATION",
                    "human_review_status": "PENDING",
                    "formal_quality_claim_allowed": False,
                }
            ).decode(),
            end="",
        )
        return experiment_exit_code(result.status, gate="automated")


def export_regressions(bundle: Path, output: Path) -> dict[str, Any]:
    verify_learning_bundle(bundle)
    evidence = load_evidence(bundle / "source")
    focus = decode_evidence_json(read_file(bundle / "regression-focus.json"))
    files = {"cases.json": evidence.raw_dataset, "focus.json": json_bytes(focus)}
    # Durable snapshots use registered target identities and cannot be silently turned into URLs.
    if evidence.verification_scope == "LOCAL_RECOMPUTED_NOT_PROVENANCE":
        snapshot = evidence.result.input_snapshot
        if snapshot is None:
            raise ValueError("frozen_configuration_required")
        config = dict(snapshot["configuration"])
        config.update(
            experiment_id="regression-" + focus["source_sha256"][:24],
            policy_path="policy.json",
            dataset={"path": "cases.json", "sha256": evidence.result.dataset_sha256},
        )
        files["experiment.json"] = json_bytes(config)
        files["policy.json"] = json_bytes(snapshot["policy"])
    else:
        report = decode_evidence_json(evidence.source_files["report.json"])
        request = dict(report["result_snapshot"]["input_snapshot"]["request"])
        request["experiment_id"] = "regression-" + focus["source_sha256"][:24]
        files["request.json"] = json_bytes(request)
    files["README.txt"] = (
        b"PRIVATE: original dataset and gold preserved byte for byte.\n"
        b"focus.json is a diagnostic focus list, not a replacement benchmark.\n"
        b"Local: python -m scripts.evaluation_workflow run --spec <this>/experiment.json "
        b"--output-dir <new-directory> --include-private\n"
        b"Durable: upload cases.json via the existing product client using registered targets.\n"
        b"Compare the full unchanged case set; no automatic model/prompt/gold edits.\n"
    )
    _publish_files(output, files)
    return {
        "status": "REGRESSION_INPUT_READY",
        "gold_modified": False,
        "evaluation_case_count": len(evidence.cases),
        "focus_case_count": focus["focus_case_count"],
        "dataset_sha256": hashlib.sha256(evidence.raw_dataset).hexdigest(),
    }


def recover_capture(directory: Path, output: Path, *, include_private: bool) -> int:
    from app.product_experiments.public_summary import PublicExperimentSummary
    from app.product_experiments.report import render_experiment_html
    from scripts.verify_product_experiment import verify_manifest

    with directory_lock(output):
        require_new_output(output)
        result, raw = load_capture(directory)
        output.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".evalops-recover-", dir=output.parent) as temporary:
            stage = Path(temporary) / "bundle"
            if isinstance(result, PublicExperimentSummary):
                if include_private:
                    raise ValueError("public_capture_has_no_private_source")
                files = {
                    "result.json": json_bytes(result.model_dump(mode="json")),
                    "report.html": render_experiment_html(result.model_dump(mode="json")).encode(
                        "utf-8"
                    ),
                }
                manifest = {
                    "schema_version": "evalops.public-experiment-manifest/1.0",
                    "export_mode": "public",
                    "experiment_id": result.experiment_id,
                    "status": result.status,
                    "private_result_sha256": result.private_result_sha256,
                    "formal_quality_claim_allowed": False,
                    "production_ready": False,
                    "files": [
                        {
                            "path": name,
                            "sha256": hashlib.sha256(data).hexdigest(),
                            "byte_size": len(data),
                        }
                        for name, data in files.items()
                    ],
                }
                _publish_files(stage, {**files, "manifest.json": json_bytes(manifest)})
                verify_manifest(stage / "manifest.json")
            else:
                write_product_artifacts(
                    result,
                    output_dir=stage,
                    command="offline capture recovery",
                    export_mode="private" if include_private else "public",
                )
                if include_private:
                    if raw is None:
                        raise ValueError("capture_dataset_required")
                    (stage / "dataset.json").write_bytes(raw)
                    load_evidence(stage)
            require_new_output(output)
            stage.rename(output)
    print(
        json_bytes(
            {
                "status": "CAPTURE_RECOVERED",
                "quality_status": result.status,
                "visibility": "PRIVATE" if include_private else "PUBLIC",
                "targets_called": 0,
                "formal_quality_claim_allowed": False,
            }
        ).decode(),
        end="",
    )
    return experiment_exit_code(result.status, gate="automated")


async def dispatch(args: argparse.Namespace) -> int:
    if args.command in {"calibrate", "regressions"} and not args.include_private:
        raise ValueError("explicit_private_export_required")
    if args.command == "init":
        initialize_demo(args.output_dir, task=args.task)
        print("DEMO_INPUT_READY: " + str(args.output_dir / "experiment.json"))
        return 0
    if args.command == "demo":
        name = "agent_tool_demo_v1" if args.task == "agent" else "product_demo_v1"
        return await run_workflow(args, ROOT / "benchmarks" / name / "experiment.json")
    if args.command == "run":
        return await run_workflow(args, args.spec)
    if args.command == "analyze":
        require_new_output(args.output_dir)
        evidence = load_evidence(args.bundle, dataset_path=args.dataset)
        traces = parse_otlp_traces(read_file(args.traces, 8 * 1024 * 1024)) if args.traces else None
        if not args.include_private:
            write_product_artifacts(
                evidence.result,
                output_dir=args.output_dir,
                command="evaluation_workflow analyze",
                export_mode="public",
            )
            status = {"verification_scope": "PUBLIC_PROJECTION_ONLY"}
        else:
            status = write_learning_bundle(
                evidence, output_dir=args.output_dir, profile=args.profile, traces=traces
            )
        print(json_bytes(status).decode(), end="")
        return experiment_exit_code(evidence.result.status, gate="automated")
    if args.command == "verify":
        manifest = decode_evidence_json(read_file(args.bundle / "manifest.json", 1024 * 1024))
        if (
            isinstance(manifest, dict)
            and manifest.get("schema_version") == "evalops.calibration-bundle/1.0"
        ):
            verified = verify_calibration_bundle(args.bundle)
        else:
            verified = verify_learning_bundle(args.bundle)
        print(json_bytes(verified).decode(), end="")
        return 0  # Integrity success, never quality success.
    if args.command == "calibrate":
        require_new_output(args.output_dir)
        verify_learning_bundle(args.bundle)
        packet_bytes = read_file(args.bundle / "review-packet.json", 128 * 1024 * 1024)
        review_bytes = read_file(args.reviews, 16 * 1024 * 1024)
        files, report = calibration_files(packet_bytes, review_bytes)
        _publish_files(args.output_dir, files)
        verify_calibration_bundle(args.output_dir)
        print(json_bytes(report.model_dump(mode="json")).decode(), end="")
        return 0
    if args.command == "regressions":
        print(json_bytes(export_regressions(args.bundle, args.output_dir)).decode(), end="")
        return 0
    if args.command == "recover":
        return recover_capture(args.bundle, args.output_dir, include_private=args.include_private)
    raise ValueError("unknown_command")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in (
        "init",
        "demo",
        "run",
        "analyze",
        "verify",
        "calibrate",
        "regressions",
        "recover",
    ):
        p = sub.add_parser(command)
        if command != "verify":
            p.add_argument(
                "--output-dir",
                type=Path,
                required=True,
                help="New directory; never overwrite existing evidence.",
            )
        if command in {"init", "demo"}:
            p.add_argument("--task", choices=("qa", "agent"), default="agent")
        if command == "run":
            p.add_argument("--spec", type=Path, required=True)
        if command in {"demo", "run", "analyze", "calibrate", "regressions", "recover"}:
            p.add_argument(
                "--include-private",
                action="store_true",
                help="Explicitly retain prompts/answers/review inputs. Never publish.",
            )
        if command in {"demo", "run", "analyze"}:
            p.add_argument("--profile", choices=PROFILES, default=PROFILES[0])
            p.add_argument("--traces", type=Path, help="Offline OTLP JSON; no network requests.")
        if command in {"demo", "run"}:
            p.add_argument("--evalops-sha")
        if command in {"analyze", "verify", "calibrate", "regressions", "recover"}:
            p.add_argument("--bundle", type=Path, required=True)
        if command == "analyze":
            p.add_argument("--dataset", type=Path)
        if command == "calibrate":
            p.add_argument("--reviews", type=Path, required=True)
    args = parser.parse_args()
    try:
        return asyncio.run(dispatch(args))
    except KeyboardInterrupt:
        print('{"error_code":"workflow_interrupted"}', file=sys.stderr)
        return 130
    except (ValueError, OSError, TypeError, KeyError):
        # Exceptions can contain private answers, URLs, or credentials: never echo them.
        print(
            '{"error_code":"workflow_input_output_or_evidence_invalid",'
            '"hint":"Check new output path, private source bundle, frozen dataset, '
            'profile, traces, and review packet identity."}',
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
