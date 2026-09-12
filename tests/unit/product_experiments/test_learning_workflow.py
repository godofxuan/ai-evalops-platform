from pathlib import Path

import pytest

from app.product_experiments.learning_workflow import load_evidence
from app.product_experiments.runner import run_experiment
from scripts.run_product_experiment import write_product_artifacts

ROOT = Path(__file__).resolve().parents[3]


async def test_local_analysis_recomputes_existing_execution_with_frozen_inputs(tmp_path: Path):
    spec = ROOT / "benchmarks/product_demo_v1/experiment.json"
    result = await run_experiment(spec, evalops_sha="e" * 40)
    write_product_artifacts(
        result, output_dir=tmp_path / "source", command="test", export_mode="private"
    )
    evidence = load_evidence(tmp_path / "source", dataset_path=spec.parent / "cases.json")
    assert evidence.verification_scope == "LOCAL_RECOMPUTED_NOT_PROVENANCE"
    assert evidence.result.model_dump(mode="json") == result.model_dump(mode="json")
    assert len(evidence.cases) == result.case_count


async def test_public_summary_cannot_be_used_as_private_diagnostic_evidence(tmp_path: Path):
    spec = ROOT / "benchmarks/product_demo_v1/experiment.json"
    result = await run_experiment(spec, evalops_sha="e" * 40)
    write_product_artifacts(result, output_dir=tmp_path / "public", command="test")
    with pytest.raises(ValueError, match="private_source_required"):
        load_evidence(tmp_path / "public", dataset_path=spec.parent / "cases.json")
