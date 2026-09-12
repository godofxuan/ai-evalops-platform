import hashlib
from pathlib import Path

import pytest

from app.product_experiments.learning_recovery import load_capture
from app.product_experiments.learning_workflow import json_bytes
from app.product_experiments.public_summary import project_public_summary
from app.product_experiments.runner import run_experiment

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("private", [False, True])
async def test_offline_capture_recovery_is_bound_to_saved_bytes_and_quality(
    tmp_path: Path, private
):
    spec = ROOT / "benchmarks/agent_tool_demo_v1/experiment.json"
    result = await run_experiment(spec, evalops_sha="e" * 40)
    result_bytes = json_bytes(result.model_dump(mode="json"))
    raw = (spec.parent / "cases.json").read_bytes()
    summary = project_public_summary(
        result, private_result_sha256=hashlib.sha256(result_bytes).hexdigest()
    )
    data = (
        {"captured-result.json": result_bytes, "captured-dataset.json": raw}
        if private
        else {"captured-public-result.json": json_bytes(summary.model_dump(mode="json"))}
    )
    status = {
        "schema_version": "evalops.workflow-capture/1.0",
        "status": "CAPTURED_NOT_EXPORTED",
        "visibility": "PRIVATE" if private else "PUBLIC",
        "original_quality_status": result.status,
        "files": {
            name: {"sha256": hashlib.sha256(value).hexdigest(), "byte_size": len(value)}
            for name, value in data.items()
        },
        "verification_scope": "CAPTURE_ONLY_NOT_VERIFIED",
        "source_provenance_verified": False,
        "formal_quality_claim_allowed": False,
        "production_ready": False,
    }
    for name, value in data.items():
        (tmp_path / name).write_bytes(value)
    (tmp_path / "capture-status.json").write_bytes(json_bytes(status))
    restored, dataset = load_capture(tmp_path)
    assert restored.status == result.status
    assert dataset == (raw if private else None)
    name = sorted(data)[0]
    (tmp_path / name).write_bytes(b"changed")
    with pytest.raises(ValueError, match="capture_file_hash_mismatch"):
        load_capture(tmp_path)
