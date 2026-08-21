import json
from pathlib import Path

from app.external_harness.dataset_identity import canonical_dataset_sha256

ROOT = Path(__file__).resolve().parents[3]
EXPECTED_DATASET_SHA256 = "08ccad71d7c96cdd2d558018b480a1e421abd3781527a828793aa4430d517d11"


def test_frozen_evidence_package_is_consistent_and_human_review_is_empty() -> None:
    dataset_path = ROOT / "benchmarks/external_harness_v1/cases.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    result = json.loads(
        (ROOT / "docs/external_harness/AUTOMATED_RESULTS.json").read_text(encoding="utf-8")
    )
    review_lines = (ROOT / "human_review/review_form.csv").read_text(encoding="utf-8").splitlines()

    assert canonical_dataset_sha256(dataset_path) == EXPECTED_DATASET_SHA256
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
