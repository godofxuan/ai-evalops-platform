"""Require real Windows file/directory symlink and junction tests, with zero skips."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

EXPECTED_CASES = frozenset(
    {"test_manifest_rejects_symlink_artifact_even_with_matching_hash"}
    | {
        f"test_linked_output_or_ancestor_is_rejected_before_target_requests[{kind}-{placement}]"
        for kind in ("symlink", "junction")
        for placement in ("output", "ancestor")
    }
)


def verify_junit(path: Path) -> int:
    cases = ElementTree.parse(path).findall(".//testcase")
    if len(cases) != len(EXPECTED_CASES) or {case.get("name") for case in cases} != EXPECTED_CASES:
        raise ValueError("missing or duplicated required Windows link cases")
    if any(case.find("skipped") is not None for case in cases):
        raise ValueError("required Windows link case skipped; privileges are not verified")
    if any(case.find("failure") is not None or case.find("error") is not None for case in cases):
        raise ValueError("required Windows link case failed")
    return len(cases)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("this acceptance gate must execute on Windows")
    if args.junit.exists():
        parser.error("evidence output must be new; do not overwrite an earlier result")
    args.junit.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/unit/scripts/test_product_experiment.py::test_manifest_rejects_symlink_artifact_even_with_matching_hash",
        "tests/unit/scripts/test_product_experiment_preflight.py::test_linked_output_or_ancestor_is_rejected_before_target_requests",
        "-q",
        "-rs",
        f"--junitxml={args.junit}",
    ]
    result = subprocess.run(command, check=False)
    if result.returncode:
        return result.returncode
    count = verify_junit(args.junit)
    print(
        json.dumps(
            {
                "status": "WINDOWS_LINK_SAFETY_VERIFIED",
                "tests": count,
                "skipped": 0,
                "platform": sys.platform,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
