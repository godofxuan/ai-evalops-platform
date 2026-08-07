import json
from pathlib import Path

import pytest

from scripts.fault_bundle import finalize_fault_bundle, validate_fault_bundle
from scripts.fault_matrix_evidence import FaultEvidenceError


def _write_complete_report(directory: Path) -> None:
    records = []
    for repetition in (1, 2, 3):
        for scenario_id in "ABCDEFGHI":
            records.append(
                {
                    "scenario_id": scenario_id,
                    "repetition": repetition,
                    "invariants_passed": True,
                    "stale_result_attempted_count": 1 if scenario_id == "C" else 0,
                    "stale_result_accepted_count": 0,
                    "stale_failure_attempted_count": 1 if scenario_id == "D" else 0,
                    "stale_failure_accepted_count": 0,
                }
            )
    directory.mkdir()
    (directory / "report.json").write_text(
        json.dumps(
            {
                "status": "verified",
                "configuration": {"source_commit": "a" * 40, "repetitions": 3},
                "results": records,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (directory / "runner.txt").write_text("runner_os=Linux\n", encoding="utf-8")


def test_fault_bundle_is_complete_and_detects_post_finalize_tampering(tmp_path: Path) -> None:
    bundle = tmp_path / "fault-run"
    _write_complete_report(bundle)

    manifest = finalize_fault_bundle(bundle)

    assert manifest["status"] == "complete"
    assert manifest["source_commit"] == "a" * 40
    assert len(manifest["files"]) == 2
    validate_fault_bundle(bundle)

    (bundle / "runner.txt").write_text("runner_os=tampered\n", encoding="utf-8")
    with pytest.raises(FaultEvidenceError):
        validate_fault_bundle(bundle)
