"""Recover and control a durable experiment without keeping the submitting process alive."""

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from app.core.strict_json import decode_evidence_json
from app.product_experiments.client import ProductAPIClient, ProductAPIError, ProductWaitTimeout
from app.product_experiments.durable_bundle import verify_durable_bundle, write_durable_bundle
from app.product_experiments.submission import DurableExperimentRequest
from scripts.run_product_experiment import experiment_exit_code


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as source:
        payload = source.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("input_file_limit")
    return payload


async def _run(args: argparse.Namespace, api_key: str) -> int:
    async with ProductAPIClient(
        args.api_url,
        api_key,
        timeout_seconds=args.request_timeout,
        max_response_bytes=args.max_response_mib * 1024 * 1024,
    ) as client:
        if args.command == "submit":
            request_payload = _read_bounded(args.request, 1024 * 1024)
            decode_evidence_json(request_payload)
            request = DurableExperimentRequest.model_validate_json(request_payload)
            accepted = await client.submit(
                request=request,
                dataset_payload=_read_bounded(args.dataset, 10 * 1024 * 1024),
                idempotency_key=args.idempotency_key,
            )
            print(accepted.model_dump_json(indent=2))
            return 0
        if args.command == "export":
            if args.include_private != (args.dataset is not None):
                raise ValueError("private_export_requires_original_dataset")
            raw = _read_bounded(args.dataset, 10 * 1024 * 1024) if args.dataset else None
            payload = await client.export(args.experiment_id, include_private=args.include_private)
            verification = write_durable_bundle(
                payload,
                output_dir=args.output_dir,
                raw_dataset=raw,
                expected_report_sha256=args.expected_report_sha256,
            )
            print(json.dumps(asdict(verification), indent=2, default=str))
            return experiment_exit_code(verification.quality_status, gate=args.gate)
        if args.command == "cancel":
            result = await client.cancel(args.experiment_id)
        elif args.command == "wait":
            result = await client.wait(
                args.experiment_id, wait_seconds=args.wait_seconds, poll_seconds=args.poll_seconds
            )
        else:
            result = await client.get(args.experiment_id)
    print(result.model_dump_json(indent=2))
    # This is an execution-state read, not a model-quality or formal gate PASS.
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url")
    parser.add_argument("--api-key-env", default="EVALOPS_API_KEY")
    parser.add_argument("--request-timeout", type=float, default=30)
    parser.add_argument("--max-response-mib", type=int, default=32)
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser(
        "verify", help="Offline integrity verification, not a quality gate"
    )
    verify.add_argument("directory", type=Path)
    verify.add_argument("--expected-report-sha256")
    export = commands.add_parser("export", help="Export evidence; exit code reflects quality gate")
    export.add_argument("experiment_id", type=UUID)
    export.add_argument("--output-dir", type=Path, required=True)
    export.add_argument("--include-private", action="store_true")
    export.add_argument("--dataset", type=Path)
    export.add_argument("--expected-report-sha256")
    export.add_argument("--gate", choices=("automated", "formal"), default="automated")
    submit = commands.add_parser("submit")
    submit.add_argument("--request", type=Path, required=True)
    submit.add_argument("--dataset", type=Path, required=True)
    submit.add_argument("--idempotency-key", required=True)
    for name in ("get", "cancel", "wait"):
        command = commands.add_parser(name)
        command.add_argument("experiment_id", type=UUID)
        if name == "wait":
            command.add_argument("--wait-seconds", type=float, default=300)
            command.add_argument("--poll-seconds", type=float, default=2)
    args = parser.parse_args()
    try:
        if args.command == "verify":
            verification = verify_durable_bundle(
                args.directory, expected_report_sha256=args.expected_report_sha256
            )
            print(json.dumps(asdict(verification), indent=2, default=str))
            return 0
        api_key = os.environ.get(args.api_key_env)
        if not api_key:
            print("api_key_environment_missing", file=sys.stderr)
            return 2
        if not args.api_url:
            raise ValueError("api_url_required")
        return asyncio.run(_run(args, api_key))
    except ProductAPIError as error:
        print(str(error), file=sys.stderr)
        if isinstance(error, ProductWaitTimeout):
            print(f"resume_experiment_id={args.experiment_id}", file=sys.stderr)
            print(f"last_observed_state={error.last_observed_state or 'UNKNOWN'}", file=sys.stderr)
            print(
                "resume_command_template=python -m scripts.product_experiment_client "
                f"--api-url <same-api-url> --api-key-env <same-env-name> wait {args.experiment_id}",
                file=sys.stderr,
            )
            return 4
        return 2
    except ValueError:
        print("invalid_client_configuration", file=sys.stderr)
        return 2
    except OSError:
        print("client_file_error", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        recovery = (
            "retry_same_submission_and_idempotency_key"
            if args.command == "submit"
            else f"resume_experiment_id={args.experiment_id}"
            if args.command != "verify"
            else "rerun_offline_verification"
        )
        print(f"client_interrupted; {recovery}", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
