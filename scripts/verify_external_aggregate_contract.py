"""Verify a pinned producer-native aggregate-only contract."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from app.product_experiments.aggregate_contract import (
    AggregateContractPin,
    verify_aggregate_contract,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pin", type=Path)
    parser.add_argument("producer_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    pin = AggregateContractPin.model_validate_json(args.pin.read_text(encoding="utf-8"))
    observed_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=args.producer_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    result = verify_aggregate_contract(
        pin, producer_root=args.producer_root, observed_publisher_sha=observed_sha
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(
        f"aggregate contract verified: {result['evidence_id']} decision={result['decision']} "
        f"formal_case_results={result['formal_case_result_status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
