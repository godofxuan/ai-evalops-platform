"""Run the real pinned checker controls; missing materials and any skip fail release."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

from app.public_benchmarks.bfcl import SOURCE_HASHES, SOURCE_SHA, prepare_pilot, validate_sources


def cache_identity() -> str:
    digest = hashlib.sha256(json.dumps(SOURCE_HASHES, sort_keys=True).encode()).hexdigest()
    return f"bfcl-{SOURCE_SHA}-{digest}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-key", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--junit", type=Path)
    args = parser.parse_args()
    if args.cache_key:
        print(cache_identity())
        return 0
    if args.root is None or args.junit is None:
        parser.error("--root and --junit required")
    validate_sources(args.root / "upstream")
    prepare_pilot(args.root)
    if args.junit.exists():
        raise ValueError("release evidence output must be new")
    args.junit.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit/public_benchmarks/test_bfcl.py",
            "tests/unit/public_benchmarks/test_pilot_report.py",
            "tests/unit/public_benchmarks/test_local_public_cli.py",
            "-q",
            "--tb=short",
            f"--junitxml={args.junit}",
        ],
        env={
            **os.environ,
            "EVALOPS_BFCL_ROOT": str(args.root.resolve()),
            "EVALOPS_RELEASE_EVIDENCE": "1",
        },
        check=False,
    )
    if result.returncode:
        return result.returncode
    cases = ElementTree.parse(args.junit).findall(".//testcase")
    if not cases or any(case.find("skipped") is not None for case in cases):
        raise ValueError("release checker tests missing or skipped")
    print(
        json.dumps(
            {
                "status": "RELEASE_CHECKER_VERIFIED",
                "tests": len(cases),
                "skipped": 0,
                "cache_key": cache_identity(),
                "model_calls": 0,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
