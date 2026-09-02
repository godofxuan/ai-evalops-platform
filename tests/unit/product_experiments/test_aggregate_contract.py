from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.product_experiments.aggregate_contract import (
    AggregateContractPin,
    verify_aggregate_contract,
)
from app.product_experiments.external_evidence import ExternalEvidenceError


def _write(path: Path, value: object) -> str:
    payload = (json.dumps(value, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _contract(tmp_path: Path) -> tuple[AggregateContractPin, str]:
    artifact = {
        "schema_version": "aggregate_v1",
        "decision": "REJECTED",
        "protocol_sha256": "d" * 64,
        "claim_boundary": ["Aggregate retrieval result only."],
        "metrics": {"recall": 0.5},
    }
    artifact_sha = _write(tmp_path / "evidence.json", artifact)
    reference = {
        "schema_version": "enterprise-rag.aggregate-evidence-reference/1.0",
        "evidence_id": "negative-v1",
        "source_repository": "https://github.com/example/rag",
        "source_sha": "a" * 40,
        "source_ci": {
            "run_id": 1,
            "url": "https://github.com/example/rag/actions/runs/1",
            "status": "completed",
            "conclusion": "success",
        },
        "artifact_path": "evidence.json",
        "artifact_sha256": artifact_sha,
        "artifact_schema": "aggregate_v1",
        "producing_code_sha": "b" * 40,
        "protocol_sha256": "d" * 64,
        "evidence_scope": "bounded validation",
        "case_count": 200,
        "decision": "REJECTED",
        "allowed_claims": ["candidate was rejected"],
        "forbidden_claims": ["candidate improved"],
        "payload_granularity": "aggregate_only",
        "formal_case_results": "INPUT_REQUIRED",
        "contains_private_case_payload": False,
    }
    reference_sha = _write(tmp_path / "reference.json", reference)
    pin = AggregateContractPin.model_validate(
        {
            "schema_version": "evalops.aggregate-contract-pin/1.0",
            "publisher_repository": "https://github.com/example/rag",
            "publisher_sha": "c" * 40,
            "publisher_ci": {
                "run_id": 2,
                "url": "https://github.com/example/rag/actions/runs/2",
                "status": "completed",
                "conclusion": "success",
            },
            "reference_path": "reference.json",
            "reference_sha256": reference_sha,
        }
    )
    return pin, "c" * 40


def test_verifies_native_negative_contract_without_synthesizing_case_results(
    tmp_path: Path,
) -> None:
    pin, sha = _contract(tmp_path)

    result = verify_aggregate_contract(pin, producer_root=tmp_path, observed_publisher_sha=sha)

    assert result["status"] == "AGGREGATE_EVIDENCE_VERIFIED"
    assert result["decision"] == "REJECTED"
    assert result["formal_case_result_status"] == "INPUT_REQUIRED"
    assert result["private_or_per_case_payload_present"] is False
    assert "case_results" not in result


def test_rejects_wrong_publisher_and_private_payload(tmp_path: Path) -> None:
    pin, sha = _contract(tmp_path)
    with pytest.raises(ExternalEvidenceError, match="checkout SHA"):
        verify_aggregate_contract(pin, producer_root=tmp_path, observed_publisher_sha="d" * 40)

    payload = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    payload["questions"] = ["secret"]
    new_sha = _write(tmp_path / "evidence.json", payload)
    reference = json.loads((tmp_path / "reference.json").read_text(encoding="utf-8"))
    reference["artifact_sha256"] = new_sha
    pin.reference_sha256 = _write(tmp_path / "reference.json", reference)
    with pytest.raises(ExternalEvidenceError, match="private/per-case"):
        verify_aggregate_contract(pin, producer_root=tmp_path, observed_publisher_sha=sha)
