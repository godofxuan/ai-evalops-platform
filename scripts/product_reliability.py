"""Private descriptive repeat panels: plan, submit, collect, report, verify."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

from app.core.strict_json import decode_evidence_json
from app.product_experiments.client import ProductAPIClient, ProductAPIError
from app.product_experiments.reliability import ReliabilityPlan
from app.product_experiments.reliability_client import (
    collect_reliability_ledger,
    create_reliability_ledger,
    read_bounded,
    report_reliability_ledger,
    submit_reliability_ledger,
    verify_reliability_ledger,
)


async def _online(args: argparse.Namespace, key: str) -> dict[str, object]:
    async with ProductAPIClient(args.api_url, key, max_response_bytes=32 * 1024 * 1024) as client:
        operation = (
            submit_reliability_ledger if args.command == "submit" else collect_reliability_ledger
        )
        return await operation(args.ledger, client)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url")
    parser.add_argument("--api-key-env", default="EVALOPS_API_KEY")
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser(
        "plan", help="Freeze private local plan before any network call"
    )
    plan_parser.add_argument("--request", type=Path, required=True)
    plan_parser.add_argument("--dataset", type=Path, required=True)
    plan_parser.add_argument("--tenant-id", type=UUID, required=True)
    plan_parser.add_argument("--trials", type=int, required=True)
    plan_parser.add_argument("--evalops-sha", required=True)
    plan_parser.add_argument("--environment-sha256", required=True)
    plan_parser.add_argument(
        "--sampling-kind", choices=("SYNTHETIC", "TARGET_DECLARED"), required=True
    )
    for name in ("submit", "collect", "report", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--ledger", type=Path, required=True)
        if name in {"report", "verify"}:
            command.add_argument("--output-dir", type=Path, required=True)
    plan_parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            request = decode_evidence_json(read_bounded(args.request, 1024 * 1024))
            plan = ReliabilityPlan.model_validate_json(
                json.dumps(
                    {
                        "panel_id": str(uuid4()),
                        "tenant_id": str(args.tenant_id),
                        "trial_count": args.trials,
                        "request": request,
                        "evalops_sha": args.evalops_sha,
                        "environment_sha256": args.environment_sha256,
                        "sampling_kind": args.sampling_kind,
                    }
                )
            )
            create_reliability_ledger(
                args.ledger, plan, read_bounded(args.dataset, 10 * 1024 * 1024)
            )
            result = {
                "plan_sha256": plan.plan_sha256,
                "expected_trials": plan.trial_count,
                "private_ledger_created": True,
                "server_preregistered": False,
            }
        elif args.command in {"report", "verify"}:
            operation = (
                report_reliability_ledger if args.command == "report" else verify_reliability_ledger
            )
            result = operation(args.ledger, args.output_dir)
        else:
            key = os.environ.get(args.api_key_env)
            if not key or not args.api_url:
                raise ValueError("api_configuration_required")
            result = asyncio.run(_online(args, key))
        print(json.dumps(result, sort_keys=True))
        return 0  # Operation succeeded, never a model-quality PASS.
    except ProductAPIError:
        print("reliability_api_error; retry_same_ledger", file=sys.stderr)
    except (ValueError, TypeError, KeyError):
        print("invalid_reliability_input", file=sys.stderr)
    except OSError:
        print("reliability_file_error", file=sys.stderr)
    except KeyboardInterrupt:
        print("reliability_interrupted; retry_same_ledger", file=sys.stderr)
        return 130
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
