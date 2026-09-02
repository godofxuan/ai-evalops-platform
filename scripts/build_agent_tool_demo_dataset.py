"""Build the deterministic 120-case Agent tool-use demo dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

CATEGORIES = (
    "single_tool",
    "multi_tool",
    "argument_validation",
    "authorization",
    "budget",
    "recovery",
)


def _call(name: str, **arguments: object) -> dict[str, object]:
    return {"name": name, "arguments": arguments, "status": "success"}


def build_cases() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for index in range(120):
        category = CATEGORIES[index % len(CATEGORIES)]
        reference = f"Agent task {index} completed."
        expected = [_call("lookup", item_id=index)]
        allowed = ["lookup"]
        maximum = 1
        baseline_calls = list(expected)
        baseline_answer = reference
        baseline_state = "completed"
        baseline_error = False
        baseline_budget = False
        if category == "multi_tool":
            expected = [_call("lookup", item_id=index), _call("summarize", item_id=index)]
            allowed = ["lookup", "summarize"]
            maximum = 2
            baseline_calls = expected[:1]
        elif category == "argument_validation":
            baseline_calls = [_call("lookup", item_id=index + 1)]
        elif category == "authorization":
            baseline_calls = [_call("admin_delete", item_id=index)]
        elif category == "budget":
            baseline_calls = [*expected, *expected]
            baseline_budget = True
        elif category == "recovery":
            baseline_calls = [
                {"name": "lookup", "arguments": {"item_id": index}, "status": "error"}
            ]
            baseline_answer = ""
            baseline_state = "failed"
            baseline_error = True
        case: dict[str, Any] = {
            "case_id": f"agent-demo-{index:03d}",
            "category": category,
            "prompt": f"Complete deterministic Agent task {index}.",
            "reference_answer": reference,
            "expected_citation_ids": [],
            "expected_tool_calls": [
                {"name": call["name"], "arguments": call["arguments"]} for call in expected
            ],
            "allowed_tools": allowed,
            "max_tool_calls": maximum,
            "metadata": {
                "fixture_profiles": {
                    "baseline": {
                        "answer": baseline_answer,
                        "latency_ms": 50 + index % 5,
                        "cost_usd": 0.012,
                        "trace_id": f"agent-baseline-{index:03d}",
                        "tool_error": baseline_error,
                        "tool_calls": baseline_calls,
                        "terminal_state": baseline_state,
                        "budget_exhausted": baseline_budget,
                    },
                    "candidate": {
                        "answer": reference,
                        "latency_ms": 52 + index % 5,
                        "cost_usd": 0.012,
                        "trace_id": f"agent-candidate-{index:03d}",
                        "tool_error": False,
                        "tool_calls": expected,
                        "terminal_state": "completed",
                        "budget_exhausted": False,
                    },
                }
            },
        }
        cases.append(case)
    return cases


def encoded_cases() -> bytes:
    return (
        json.dumps(build_cases(), ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/agent_tool_demo_v1/cases.json")
    )
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    payload = encoded_cases()
    digest = hashlib.sha256(payload).hexdigest()
    if args.verify:
        if not args.output.exists() or args.output.read_bytes() != payload:
            print(f"agent tool dataset drift: {args.output}")
            return 1
        print(f"agent tool dataset verified: 120 cases; sha256={digest}")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    print(f"agent tool dataset written: 120 cases; sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
