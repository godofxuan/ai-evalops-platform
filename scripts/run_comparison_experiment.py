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
        description="Generate improvement, decline, new-failure, and recovery diffs."
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key-env", default="EVALOPS_EXPERIMENT_API_KEY")
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--deadline-seconds", type=float, default=300)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/results/phase_9_run_comparison.json"),
    )
    return parser


async def _run(args: argparse.Namespace) -> dict[str, object]:
    cases = [
        {
            "case_id": "improvement",
            "question": "synthetic improvement",
            "expected_answer": "correct",
            "metadata": {
                "mock_profiles": {
                    "left": {"answer": "incorrect"},
                    "right": {"answer": "correct"},
                }
            },
        },
        {
            "case_id": "decline",
            "question": "synthetic decline",
            "expected_answer": "correct",
            "metadata": {
                "mock_profiles": {
                    "left": {"answer": "correct"},
                    "right": {"answer": "incorrect"},
                }
            },
        },
        {
            "case_id": "new-failure",
            "question": "synthetic new failure",
            "expected_answer": "correct",
            "metadata": {
                "mock_profiles": {
                    "left": {"answer": "correct"},
                    "right": {"outcome": "permanent_failure"},
                }
            },
        },
        {
            "case_id": "recovery",
            "question": "synthetic recovery",
            "expected_answer": "correct",
            "metadata": {
                "mock_profiles": {
                    "left": {"outcome": "permanent_failure"},
                    "right": {"answer": "correct"},
                }
            },
        },
    ]
    report = experiment_envelope(
        experiment="run_comparison",
        configuration={"api_url": args.api_url, "case_count": len(cases)},
    )
    async with ExperimentClient(
        api_url=args.api_url,
        api_key_env=args.api_key_env,
        timeout_seconds=30,
    ) as client:
        version_id = await client.create_dataset_version(
            name_prefix="phase9-comparison",
            cases=cases,
        )
        left = await client.create_run(
            dataset_version_id=version_id,
            target_config={"profile": "left"},
            evaluator_config={"max_attempts": 1},
        )
        right = await client.create_run(
            dataset_version_id=version_id,
            target_config={"profile": "right"},
            evaluator_config={"max_attempts": 1},
        )
        await asyncio.gather(
            client.wait_for_run(
                str(left["id"]),
                poll_seconds=args.poll_seconds,
                deadline_seconds=args.deadline_seconds,
            ),
            client.wait_for_run(
                str(right["id"]),
                poll_seconds=args.poll_seconds,
                deadline_seconds=args.deadline_seconds,
            ),
        )
        comparison = await client.compare_runs(str(left["id"]), str(right["id"]))
    report["results"].append(
        {
            "left_run_id": left["id"],
            "right_run_id": right["id"],
            "comparison": comparison,
        }
    )
    report["status"] = "completed"
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
