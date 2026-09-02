"""Verify a public external aggregate artifact without inventing per-case evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.product_experiments.external_evidence import (
    ExternalEvidenceError,
    verify_external_aggregate_evidence_files,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = verify_external_aggregate_evidence_files(args.reference, args.evidence)
    except ExternalEvidenceError as error:
        print(f"external aggregate evidence verification failed: {error}")
        return 1
    rendered = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(
        f"external aggregate evidence verified: {result['evidence_id']} "
        f"status={result['status']} formal_case_results={result['formal_case_result_status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
