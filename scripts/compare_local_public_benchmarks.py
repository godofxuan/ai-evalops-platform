"""Compare frozen public benchmark runs offline; never invoke models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.public_benchmarks.pilot_report import verify_comparison, write_comparison


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("compare", "verify"))
    parser.add_argument("--run-dir", type=Path, action="append", required=True)
    parser.add_argument("--report-dir", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bfcl-source-dir", type=Path)
    args = parser.parse_args()
    if len(args.run_dir) != len(args.report_dir):
        parser.error("each --run-dir needs a corresponding --report-dir in the same order")
    sources = list(zip(args.run_dir, args.report_dir, strict=True))
    if args.operation == "compare":
        result = write_comparison(sources, args.output_dir, args.bfcl_source_dir)
    else:
        result = verify_comparison(args.output_dir, sources, args.bfcl_source_dir)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
