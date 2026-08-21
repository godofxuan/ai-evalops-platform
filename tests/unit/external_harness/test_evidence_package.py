import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXPECTED_DATASET_SHA256 = "8963cc0385af516d076d992497a02770c2fef3fc8e0039706d7d7b8a086a686c"


def test_frozen_evidence_package_is_consistent_and_human_review_is_empty() -> None:
    dataset_path = ROOT / "benchmarks/external_harness_v1/cases.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    result = json.loads(
        (ROOT / "docs/external_harness/AUTOMATED_RESULTS.json").read_text(encoding="utf-8")
    )
    review_lines = (ROOT / "human_review/review_form.csv").read_text(encoding="utf-8").splitlines()

    assert hashlib.sha256(dataset_path.read_bytes()).hexdigest() == EXPECTED_DATASET_SHA256
    assert result["dataset_sha256"] == EXPECTED_DATASET_SHA256
    assert result["status"] == "INPUT_BLOCKED"
    assert result["formal_ab_executed"] is False
    assert dataset["formal_quality_gate_eligible"] is False
    assert len(dataset["cases"]) == 9
    assert len({case["category"] for case in dataset["cases"]}) == 9
    assert review_lines == [
        "packet_id,reviewer_id,case_id,answer_label,groundedness,"
        "citation_correctness,tool_correctness,safety_refusal,overall,notes"
    ]
