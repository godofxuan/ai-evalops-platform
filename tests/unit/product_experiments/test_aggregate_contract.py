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


def test_aggregate_rejects_duplicate_keys_even_when_hashes_match(tmp_path: Path) -> None:
    pin, sha = _contract(tmp_path)
    path = tmp_path / "evidence.json"
    payload = b'{"decision":"ACCEPTED",' + path.read_bytes()[1:]
    path.write_bytes(payload)
    reference = json.loads((tmp_path / "reference.json").read_text())
    reference["artifact_sha256"] = hashlib.sha256(payload).hexdigest()
    pin.reference_sha256 = _write(tmp_path / "reference.json", reference)
    with pytest.raises(ExternalEvidenceError, match="JSON"):
        verify_aggregate_contract(pin, producer_root=tmp_path, observed_publisher_sha=sha)


def test_aggregate_reference_read_has_a_byte_limit(tmp_path: Path) -> None:
    pin, sha = _contract(tmp_path)
    path = tmp_path / "reference.json"
    payload = path.read_bytes() + b" " * (1024 * 1024)
    path.write_bytes(payload)
    pin.reference_sha256 = hashlib.sha256(payload).hexdigest()
    with pytest.raises(ExternalEvidenceError, match="size limit"):
        verify_aggregate_contract(pin, producer_root=tmp_path, observed_publisher_sha=sha)


def test_aggregate_rejects_overflowing_json_number(tmp_path: Path) -> None:
    pin, sha = _contract(tmp_path)
    path = tmp_path / "evidence.json"
    payload = path.read_bytes().replace(b"0.5", b"1e999")
    path.write_bytes(payload)
    reference = json.loads((tmp_path / "reference.json").read_text())
    reference["artifact_sha256"] = hashlib.sha256(payload).hexdigest()
    pin.reference_sha256 = _write(tmp_path / "reference.json", reference)
    with pytest.raises(ExternalEvidenceError, match="JSON"):
        verify_aggregate_contract(pin, producer_root=tmp_path, observed_publisher_sha=sha)


@pytest.mark.parametrize(
    "field,value", [("schema_version", "unexpected_schema"), ("case_count", 1)]
)
def test_rehashed_aggregate_must_match_declared_schema_and_count(
    tmp_path: Path, field: str, value: object
) -> None:
    pin, sha = _contract(tmp_path)
    payload = json.loads((tmp_path / "evidence.json").read_text())
    payload[field] = value
    reference = json.loads((tmp_path / "reference.json").read_text())
    reference["artifact_sha256"] = _write(tmp_path / "evidence.json", payload)
    pin.reference_sha256 = _write(tmp_path / "reference.json", reference)
    with pytest.raises(ExternalEvidenceError, match="schema|case.count"):
        verify_aggregate_contract(pin, producer_root=tmp_path, observed_publisher_sha=sha)


def test_v2_aggregate_has_strict_structure_without_claiming_online_or_privacy_audit(
    tmp_path: Path,
) -> None:
    pin, sha = _contract(tmp_path)
    reference = json.loads((tmp_path / "reference.json").read_text())
    payload = {
        "schema_version": "evalops.aggregate-summary/2.0",
        "source_repository": reference["source_repository"],
        "source_sha": reference["source_sha"],
        "producing_code_sha": reference["producing_code_sha"],
        "protocol_sha256": reference["protocol_sha256"],
        "evidence_scope": reference["evidence_scope"],
        "case_count": 200,
        "decision": "REJECTED",
        "claim_boundary": {
            "allowed": reference["allowed_claims"],
            "forbidden": reference["forbidden_claims"],
        },
        "metrics": {"recall": 0.5},
    }
    reference["artifact_schema"] = payload["schema_version"]
    reference["artifact_sha256"] = _write(tmp_path / "evidence.json", payload)
    pin_values = pin.model_dump(mode="json")
    pin_values.update(
        schema_version="evalops.aggregate-contract-pin/2.0",
        reference_sha256=_write(tmp_path / "reference.json", reference),
    )
    pin = AggregateContractPin.model_validate_json(json.dumps(pin_values))
    result = verify_aggregate_contract(pin, producer_root=tmp_path, observed_publisher_sha=sha)
    assert result["verification_level"] == "STRICT_AGGREGATE_SCHEMA"
    assert result["online_verification_status"] == "NOT_RUN"
    assert result["privacy_assurance"] == "STRUCTURE_ONLY_NOT_CONTENT_AUDIT"
    assert "private_or_per_case_payload_present" not in result
    payload["metrics"]["unknown_nested"] = {"opaque": "hidden case content"}
    reference["artifact_sha256"] = _write(tmp_path / "evidence.json", payload)
    pin.reference_sha256 = _write(tmp_path / "reference.json", reference)
    with pytest.raises(ExternalEvidenceError, match="schema"):
        verify_aggregate_contract(pin, producer_root=tmp_path, observed_publisher_sha=sha)


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


def test_accepts_named_protocol_digest_without_weakening_case_boundary(tmp_path: Path) -> None:
    pin, sha = _contract(tmp_path)
    payload = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    payload["fp16_optimization_protocol_sha256"] = payload.pop("protocol_sha256")
    artifact_sha = _write(tmp_path / "evidence.json", payload)
    reference = json.loads((tmp_path / "reference.json").read_text(encoding="utf-8"))
    reference["artifact_sha256"] = artifact_sha
    pin.reference_sha256 = _write(tmp_path / "reference.json", reference)

    result = verify_aggregate_contract(pin, producer_root=tmp_path, observed_publisher_sha=sha)

    assert result["status"] == "AGGREGATE_EVIDENCE_VERIFIED"
    assert result["formal_case_result_status"] == "INPUT_REQUIRED"
    assert result["formal_quality_claim_allowed"] is False
    assert "case_results" not in result


def test_rejects_reference_protocol_absent_from_named_protocol_digests(
    tmp_path: Path,
) -> None:
    pin, sha = _contract(tmp_path)
    payload = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    payload["fp16_optimization_protocol_sha256"] = "e" * 64
    payload.pop("protocol_sha256")
    artifact_sha = _write(tmp_path / "evidence.json", payload)
    reference = json.loads((tmp_path / "reference.json").read_text(encoding="utf-8"))
    reference["artifact_sha256"] = artifact_sha
    pin.reference_sha256 = _write(tmp_path / "reference.json", reference)

    with pytest.raises(ExternalEvidenceError, match="protocol"):
        verify_aggregate_contract(pin, producer_root=tmp_path, observed_publisher_sha=sha)


def test_accepts_nested_protocol_and_exact_structured_claim_boundary(tmp_path: Path) -> None:
    pin, sha = _contract(tmp_path)
    payload = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    payload["protocol"] = {"path": "protocol.json", "sha256": payload.pop("protocol_sha256")}
    payload["claim_boundary"] = {
        "allowed": ["candidate was rejected"],
        "forbidden": ["candidate improved"],
    }
    artifact_sha = _write(tmp_path / "evidence.json", payload)
    reference = json.loads((tmp_path / "reference.json").read_text(encoding="utf-8"))
    reference["artifact_sha256"] = artifact_sha
    pin.reference_sha256 = _write(tmp_path / "reference.json", reference)

    result = verify_aggregate_contract(pin, producer_root=tmp_path, observed_publisher_sha=sha)

    assert result["status"] == "AGGREGATE_EVIDENCE_VERIFIED"
    assert result["source_claim_boundary"] == payload["claim_boundary"]
    assert result["formal_case_result_status"] == "INPUT_REQUIRED"
    assert "case_results" not in result


def test_rejects_structured_claim_boundary_drift(tmp_path: Path) -> None:
    pin, sha = _contract(tmp_path)
    payload = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    payload["claim_boundary"] = {
        "allowed": ["candidate was promoted"],
        "forbidden": ["candidate improved"],
    }
    artifact_sha = _write(tmp_path / "evidence.json", payload)
    reference = json.loads((tmp_path / "reference.json").read_text(encoding="utf-8"))
    reference["artifact_sha256"] = artifact_sha
    pin.reference_sha256 = _write(tmp_path / "reference.json", reference)

    with pytest.raises(ExternalEvidenceError, match="claim boundary"):
        verify_aggregate_contract(pin, producer_root=tmp_path, observed_publisher_sha=sha)
