"""Exercise learning diagnostics over actual durable bundles produced by integration workers."""

import json
from pathlib import Path

from app.product_experiments.learning_bundle import verify_learning_bundle, write_learning_bundle
from app.product_experiments.learning_workflow import load_evidence


def exercise_learning_bundle(source: Path, *, task: str, scenario: str, trial: int) -> None:
    evidence = load_evidence(source)
    assert evidence.verification_scope == "PRIVATE_RECOMPUTED"
    # The source is ledger/trial-N. Diagnostics must not mutate the strict ledger.
    ledger = source.parent
    output = ledger.parent / f"{ledger.name}-learning-{trial:02d}"
    verified = write_learning_bundle(evidence, output_dir=output)
    assert verify_learning_bundle(output) == verified
    report = json.loads((output / "analysis.json").read_bytes())
    expected_observed = sum(len(arm) for arm in evidence.result.observations.values())
    assert report["observed_arm_count"] == expected_observed
    assert report["missing_arm_count"] == len(evidence.cases) * 2 - expected_observed
    assert report["original_quality_status"] == evidence.result.status
    assert report["formal_quality_claim_allowed"] is False
    focus = json.loads((output / "regression-focus.json").read_bytes())
    assert focus["evaluation_case_count"] == len(evidence.cases)
    assert focus["gold_modified"] is False
    assert (output / "source/dataset.json").read_bytes() == evidence.raw_dataset
    print(
        f"SYNTHETIC_LEARNING_WORKFLOW_VERIFIED task={task} scenario={scenario} "
        f"trial={trial} private_recomputed=true diagnostics_recomputed=true"
    )
