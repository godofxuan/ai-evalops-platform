"""Build the deterministic 120-case product demo dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

CATEGORIES = (
    "basic",
    "semantic",
    "completeness",
    "conflicting_information",
    "high_level",
    "information_not_found",
)


def build_cases() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for index in range(120):
        category = CATEGORIES[index % len(CATEGORIES)]
        reference = (
            "No supported answer was found."
            if category == "information_not_found"
            else f"Verified answer {index}."
        )
        source_id = f"source-{index:03d}"
        baseline_regression = index % 10 == 0
        cases.append(
            {
                "case_id": f"demo-{index:03d}",
                "category": category,
                "prompt": f"Demo {category} question {index}?",
                "reference_answer": reference,
                "expected_citation_ids": [source_id],
                "metadata": {
                    "fixture_profiles": {
                        "baseline": {
                            "answer": "Unsupported baseline answer."
                            if baseline_regression
                            else reference,
                            "citations": [] if baseline_regression else [{"source_id": source_id}],
                            "latency_ms": 40 + index % 7,
                            "cost_usd": 0.01,
                            "trace_id": f"demo-baseline-{index:03d}",
                            "tool_error": False,
                        },
                        "candidate": {
                            "answer": reference,
                            "citations": [{"source_id": source_id}],
                            "latency_ms": 44 + index % 7,
                            "cost_usd": 0.011,
                            "trace_id": f"demo-candidate-{index:03d}",
                            "tool_error": False,
                        },
                    }
                },
            }
        )
    return cases


def encoded_cases() -> bytes:
    return (
        json.dumps(
            build_cases(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/product_demo_v1/cases.json"),
    )
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    payload = encoded_cases()
    digest = hashlib.sha256(payload).hexdigest()
    if args.verify:
        if not args.output.exists() or args.output.read_bytes() != payload:
            print(f"demo dataset drift: {args.output}")
            return 1
        print(f"demo dataset verified: {len(build_cases())} cases; sha256={digest}")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    print(f"demo dataset written: {len(build_cases())} cases; sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
