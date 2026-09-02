from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.product_experiments.runner import ProductExperimentResult
from scripts.run_product_experiment import write_product_artifacts
from scripts.verify_product_experiment import ProductManifestError, verify_manifest


def test_product_artifacts_have_hash_manifest_and_claim_boundary(tmp_path: Path) -> None:
    result = ProductExperimentResult(
        experiment_id="input-required",
        status="INPUT_REQUIRED",
        scope="FORMAL",
        dataset_sha256="d" * 64,
        evalops_sha="e" * 40,
        case_count=120,
        source_identities={
            "baseline": {
                "repository": "https://example.com/rag",
                "sha": "b" * 40,
                "provider_type": "fixture",
            }
        },
        arms={},
        automated_assessment={"status": "NOT_RUN"},
        case_comparisons=[],
        input_requirements=[
            {
                "arm": "candidate",
                "code": "MISSING_CREDENTIAL_ENV",
                "environment_variable": "CANDIDATE_RAG_TOKEN",
            }
        ],
    )

    manifest = write_product_artifacts(
        result,
        output_dir=tmp_path,
        command="test command",
    )

    persisted = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert {entry["path"] for entry in persisted["files"]} == {"result.json", "report.html"}
    assert manifest["formal_quality_claim_allowed"] is False
    assert persisted["human_review_status"] == "PENDING"
    assert persisted["production_ready"] is False
    assert verify_manifest(tmp_path / "manifest.json")["status"] == "INPUT_REQUIRED"


def test_product_manifest_rejects_tampered_result(tmp_path: Path) -> None:
    result = ProductExperimentResult(
        experiment_id="demo",
        status="DEMO_PASS",
        scope="DEMO",
        dataset_sha256="d" * 64,
        evalops_sha="e" * 40,
        case_count=0,
        source_identities={
            "baseline": {
                "repository": "demo://baseline",
                "sha": "b" * 40,
                "provider_type": "fixture",
            }
        },
        arms={},
        automated_assessment={"status": "PASS"},
        case_comparisons=[],
    )
    write_product_artifacts(result, output_dir=tmp_path, command="test command")
    (tmp_path / "result.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ProductManifestError, match="size mismatch|digest mismatch"):
        verify_manifest(tmp_path / "manifest.json")
