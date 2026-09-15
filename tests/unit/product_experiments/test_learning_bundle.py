import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.product_experiments.durable_bundle import write_durable_bundle
from app.product_experiments.durable_report import build_durable_report
from app.product_experiments.export_service import encode_report
from app.product_experiments.learning_bundle import verify_learning_bundle, write_learning_bundle
from app.product_experiments.learning_workflow import json_bytes, load_evidence
from app.product_experiments.runner import run_experiment
from scripts.run_product_experiment import write_product_artifacts
from tests.unit.product_experiments.test_durable_report import durable_evidence as durable_evidence
from tests.unit.product_experiments.test_submission import submission_inputs as submission_inputs

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
async def local_evidence(tmp_path: Path):
    spec = ROOT / "benchmarks/agent_tool_demo_v1/experiment.json"
    result = await run_experiment(spec, evalops_sha="e" * 40)
    write_product_artifacts(
        result, output_dir=tmp_path / "source", command="test", export_mode="private"
    )
    return load_evidence(tmp_path / "source", dataset_path=spec.parent / "cases.json")


async def test_actual_local_execution_diagnostics_roundtrip_and_no_overwrite(
    local_evidence, tmp_path
):
    output = tmp_path / "analysis"
    verified = write_learning_bundle(local_evidence, output_dir=output)
    assert verified["verification_scope"] == "LOCAL_RECOMPUTED_NOT_PROVENANCE"
    assert verify_learning_bundle(output) == verified
    with pytest.raises(ValueError, match="output_already_exists"):
        write_learning_bundle(local_evidence, output_dir=output)
    assert verify_learning_bundle(output) == verified


@pytest.mark.parametrize(
    "filename", ["analysis.json", "report.html", "review-packet.json", "regression-focus.json"]
)
async def test_rehashed_diagnostics_cannot_bypass_offline_reconstruction(
    local_evidence,
    tmp_path: Path,
    filename: str,
):
    output = tmp_path / "analysis"
    write_learning_bundle(local_evidence, output_dir=output)
    payload = b"forged interpretation"
    (output / filename).write_bytes(payload)
    manifest = json.loads((output / "manifest.json").read_bytes())
    manifest["files"][filename] = {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "byte_size": len(payload),
    }
    (output / "manifest.json").write_bytes(json_bytes(manifest))
    with pytest.raises(ValueError, match="diagnostic_recomputation"):
        verify_learning_bundle(output)


async def test_durable_accepted_snapshot_uses_existing_private_recomputation(
    durable_evidence, tmp_path
):
    snapshot, raw = durable_evidence
    report = encode_report(build_durable_report(snapshot=snapshot, raw_dataset=raw))
    write_durable_bundle(report, output_dir=tmp_path / "durable", raw_dataset=raw)
    evidence = load_evidence(tmp_path / "durable")
    verified = write_learning_bundle(evidence, output_dir=tmp_path / "analysis")
    assert verified["verification_scope"] == "PRIVATE_RECOMPUTED"
    assert verified["source_provenance_verified"] is False
    assert verified["quality_status"] == evidence.result.status
    # This fixture validates recomputation compatibility, not a real database run.
    assert verify_learning_bundle(tmp_path / "analysis") == verified


async def test_durable_regression_export_keeps_full_source_and_registered_targets(
    durable_evidence,
    tmp_path,
):
    from scripts.evaluation_workflow import export_regressions

    snapshot, raw = durable_evidence
    report = encode_report(build_durable_report(snapshot=snapshot, raw_dataset=raw))
    write_durable_bundle(report, output_dir=tmp_path / "durable", raw_dataset=raw)
    write_learning_bundle(load_evidence(tmp_path / "durable"), output_dir=tmp_path / "analysis")
    exported = export_regressions(tmp_path / "analysis", tmp_path / "regression")
    assert exported["gold_modified"] is False
    assert (tmp_path / "regression/cases.json").read_bytes() == raw
    assert not (tmp_path / "regression/experiment.json").exists()
    request = json.loads((tmp_path / "regression/request.json").read_bytes())
    assert request["source_dataset_sha256"] == hashlib.sha256(raw).hexdigest()


async def test_manifest_boolean_claims_are_strict(local_evidence, tmp_path):
    output = tmp_path / "analysis"
    write_learning_bundle(local_evidence, output_dir=output)
    manifest = json.loads((output / "manifest.json").read_bytes())
    manifest["formal_quality_claim_allowed"] = 0
    (output / "manifest.json").write_bytes(json_bytes(manifest))
    with pytest.raises(ValueError, match="workflow_manifest_invalid"):
        verify_learning_bundle(output)


async def test_source_paths_are_validated_before_any_public_library_write(local_evidence, tmp_path):
    sentinel = tmp_path / "outside.txt"
    sentinel.write_bytes(b"preserve")
    unsafe = replace(
        local_evidence,
        source_files={**local_evidence.source_files, "../../../outside.txt": b"must-not-write"},
    )
    with pytest.raises(ValueError, match="unsafe_source_file_name"):
        write_learning_bundle(unsafe, output_dir=tmp_path / "analysis")
    assert sentinel.read_bytes() == b"preserve"
    assert not (tmp_path / "analysis").exists()
