from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.external_harness.review_kit import validate_completed_reviews
from human_review.validate_reviews import expected_cases, load_rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and emit canonical review JSON; does not mutate EvalOps"
    )
    parser.add_argument("reviews", type=Path)
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    rows = load_rows(args.reviews)
    validate_completed_reviews(rows, expected_case_ids=expected_cases(args.dataset))
    print(json.dumps([row.model_dump(mode="json") for row in rows], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
