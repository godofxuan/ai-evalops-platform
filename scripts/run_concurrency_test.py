import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from scripts.experiment_support import (
    ExperimentClient,
    ExperimentError,
    experiment_envelope,
    write_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Submit concurrent requests with one Idempotency-Key."
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key-env", default="EVALOPS_EXPERIMENT_API_KEY")
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--cases", type=int, default=10)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/results/phase_9_idempotency_concurrency.json"),
    )
    return parser


async def _run(args: argparse.Namespace) -> dict[str, object]:
    if not 1 <= args.requests <= 100:
        raise ExperimentError("requests must be within [1, 100]")
    report = experiment_envelope(
        experiment="idempotency_concurrency",
        configuration={
            "requests": args.requests,
            "cases": args.cases,
            "api_url": args.api_url,
        },
    )
    cases = [
        {
            "case_id": f"idempotency-{index:03d}",
            "question": f"synthetic idempotency case {index}",
            "expected_answer": "mock answer",
            "metadata": {},
        }
        for index in range(args.cases)
    ]
    async with ExperimentClient(
        api_url=args.api_url,
        api_key_env=args.api_key_env,
        timeout_seconds=30,
    ) as client:
        version_id = await client.create_dataset_version(
            name_prefix="phase9-idempotency",
            cases=cases,
        )
        responses = await client.concurrent_create(
            count=args.requests,
            dataset_version_id=version_id,
            idempotency_key=f"phase9-concurrent-{datetime.now(UTC).timestamp()}",
        )
    status_codes = [response.status_code for response in responses]
    run_ids = {
        str(response.json().get("id"))
        for response in responses
        if response.is_success and isinstance(response.json(), dict)
    }
    result = {
        "request_count": len(responses),
        "status_codes": status_codes,
        "distinct_run_ids": sorted(run_ids),
        "http_500_count": sum(code >= 500 for code in status_codes),
        "accepted_count": sum(code == 202 for code in status_codes),
    }
    report["results"].append(result)
    report["status"] = (
        "completed" if len(run_ids) == 1 and set(status_codes) == {202} else "assertion_failed"
    )
    report["finished_at"] = datetime.now(UTC).isoformat()
    return report


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = asyncio.run(_run(args))
        write_report(args.output, report)
    except (ExperimentError, OSError) as error:
        print(f"experiment failed: {error}")
        return 1
    print(f"preserved experiment result: {args.output}")
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
