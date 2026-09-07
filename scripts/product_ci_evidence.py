"""Retain test identities/outcomes and an allowlisted CI identity, never payload logs."""

import argparse
import hashlib
import json
import os
import platform
import re
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REQUIRED = ("junit-unit.xml", "junit-product-experiment-persistence.xml")


def _safe_id(value: str) -> str:
    return re.sub(r"[^\w.\[\]():/ -]", "_", value)[:500]


def capture(output: Path, junit_dir: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    evidence: dict[str, Any] = {}
    for name in sorted(set(REQUIRED) | {path.name for path in junit_dir.glob("junit-*.xml")}):
        source = junit_dir / name
        if not source.is_file():
            evidence[name] = {"state": "NOT_GENERATED"}
            continue
        raw = source.read_bytes()
        entry: dict[str, Any] = {"source_sha256": hashlib.sha256(raw).hexdigest()}
        evidence[name] = entry
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            entry["state"] = "MALFORMED_NOT_VERIFIED"
            continue
        suite = ET.Element("testsuite", name=name)
        phase_pattern = (
            r"SYNTHETIC_OBSERVATION_FAULT_VERIFIED task=(?:QA|AGENT_TOOL_USE) "
            r"fault=(?:answer|terminal) jobs=4 failed=1 accepted=3 "
            r"attempts_each=1 private_recomputed=true"
        )
        entry["verified_synthetic_phases"] = sorted(
            set(re.findall(phase_pattern, raw.decode("utf-8", errors="replace")))
        )
        counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        for test in root.iter("testcase"):
            counts["tests"] += 1
            item = ET.SubElement(
                suite,
                "testcase",
                {
                    key: _safe_id(test.get(key, ""))
                    for key in ("classname", "name", "file", "line", "time")
                },
            )
            for tag, count in (
                ("failure", "failures"),
                ("error", "errors"),
                ("skipped", "skipped"),
            ):
                if test.find(tag) is not None:
                    counts[count] += 1
                    ET.SubElement(item, tag, message="Body omitted; see controlled CI job log.")
        suite.attrib.update({key: str(value) for key, value in counts.items()})
        ET.ElementTree(suite).write(output / name, encoding="utf-8", xml_declaration=True)
        entry["counts"] = counts
        entry["state"] = (
            "EMPTY_NOT_VERIFIED"
            if not counts["tests"]
            else "FAILED"
            if counts["failures"] or counts["errors"]
            else "PASSED_WITH_SKIPS"
            if counts["skipped"]
            else "PASSED"
        )
        entry["retained_sha256"] = hashlib.sha256((output / name).read_bytes()).hexdigest()
    lock = Path(__file__).resolve().parents[1] / "uv.lock"
    identity: dict[str, Any] = {
        "schema_version": "evalops.ci-closeout-evidence/1.0",
        "code_sha": os.getenv("GITHUB_SHA"),
        "workflow": os.getenv("GITHUB_WORKFLOW"),
        "run_id": os.getenv("GITHUB_RUN_ID"),
        "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "job": os.getenv("GITHUB_JOB"),
        "generated_at": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "commands": [
            'uv run --no-sync pytest -m "not integration" --junitxml=/tmp/junit-unit.xml',
            "uv run --no-sync pytest tests/integration/test_product_experiment_persistence.py "
            "-o junit_logging=system-out --junitxml=/tmp/junit-product-experiment-persistence.xml",
        ],
        "junit": evidence,
        "redaction": "Test IDs/outcomes and allowlisted synthetic fault phases only; no payloads.",
        "scope": "Synthetic fixtures; real PostgreSQL/local TCP; test-only DNS/public peer.",
        "formal_quality_claim_allowed": False,
        "production_ready": False,
    }
    (output / "identity.json").write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    return identity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--junit-dir", type=Path, default=Path("/tmp"))
    args = parser.parse_args()
    identity = capture(args.output_dir, args.junit_dir)
    print(json.dumps({"code_sha": identity["code_sha"], "junit": identity["junit"]}))
    return 0  # Capture success is not test success; every source outcome is explicit.


if __name__ == "__main__":
    raise SystemExit(main())
