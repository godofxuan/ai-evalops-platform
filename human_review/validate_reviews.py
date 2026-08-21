from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

from app.external_harness.review_kit import ReviewRow, validate_completed_reviews

ROOT = Path(__file__).resolve().parents[1]


def load_rows(path: Path) -> list[ReviewRow]:
    with path.open(encoding="utf-8", newline="") as stream:
        return [
            ReviewRow.model_validate(
                {
                    **row,
                    **{
                        key: int(row[key])
                        for key in (
                            "groundedness",
                            "citation_correctness",
                            "tool_correctness",
                            "safety_refusal",
                        )
                    },
                }
            )
            for row in csv.DictReader(stream)
        ]


def expected_cases(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {item["id"] for item in payload["cases"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate genuine blinded review rows")
    parser.add_argument("--reviews", type=Path, default=ROOT / "human_review/review_form.csv")
    parser.add_argument(
        "--dataset", type=Path, default=ROOT / "benchmarks/external_harness_v1/cases.json"
    )
    parser.add_argument("--allow-pending", action="store_true")
    args = parser.parse_args()
    rows = load_rows(args.reviews)
    if not rows:
        print(json.dumps({"status": "PENDING", "reviewers": 0, "cases": 0}))
        return 0 if args.allow_pending else 2
    summary = validate_completed_reviews(rows, expected_case_ids=expected_cases(args.dataset))
    print(json.dumps({"status": "COMPLETE", **asdict(summary)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
