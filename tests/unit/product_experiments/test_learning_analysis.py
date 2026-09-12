from pathlib import Path

from app.product_experiments.learning_analysis import build_analysis
from app.product_experiments.learning_workflow import load_evidence
from app.product_experiments.runner import run_experiment
from scripts.run_product_experiment import write_product_artifacts

ROOT = Path(__file__).resolve().parents[3]


async def test_actual_agent_run_explains_every_arm_and_preserves_gate(tmp_path: Path):
    spec = ROOT / "benchmarks/agent_tool_demo_v1/experiment.json"
    result = await run_experiment(spec, evalops_sha="e" * 40)
    write_product_artifacts(
        result, output_dir=tmp_path / "source", command="test", export_mode="private"
    )
    evidence = load_evidence(tmp_path / "source", dataset_path=spec.parent / "cases.json")
    report = build_analysis(evidence)
    assert report["original_quality_status"] == result.status
    assert report["formal_quality_claim_allowed"] is False
    assert report["observed_arm_count"] == result.case_count * 2
    assert len(report["cases"]) == result.case_count
    assert any(row["baseline"]["findings"] for row in report["cases"])
    assert all(
        row["candidate"]["trace"]["evidence_status"] == "NOT_SUPPLIED" for row in report["cases"]
    )
