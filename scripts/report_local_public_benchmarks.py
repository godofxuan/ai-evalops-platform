"""Create or independently recompute a local public pilot report, with zero model calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.public_benchmarks.pilot_report import verify_report, write_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report")
    report.add_argument("--run-dir", required=True, type=Path)
    report.add_argument("--output-dir", required=True, type=Path)
    report.add_argument("--bfcl-source-dir", type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("--run-dir", required=True, type=Path)
    verify.add_argument("--report-dir", required=True, type=Path)
    verify.add_argument("--bfcl-source-dir", type=Path)
    args = parser.parse_args()
    if args.command == "report":
        outcome = write_report(args.run_dir, args.output_dir, args.bfcl_source_dir)
    else:
        outcome = verify_report(args.report_dir, args.run_dir, args.bfcl_source_dir)
    print(json.dumps(outcome, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
