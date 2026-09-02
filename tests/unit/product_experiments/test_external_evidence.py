from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.product_experiments.external_evidence import (
    ExternalAggregateEvidenceReference,
    ExternalEvidenceError,
    verify_external_aggregate_evidence,
)


def _evidence() -> dict[str, object]:
    return {
        "schema_version": "uda_finance_r5_public_v1",
        "evaluation_scope": "fresh_known_report_page_localization",
        "decision": "PROMOTED_FINANCE_KNOWN_REPORT_DEFAULT",
        "code_revision": "c" * 40,
        "protocol_sha256": "b" * 64,
        "baseline": {
            "case_count": 192,
            "page_hit_at_5": 154 / 192,
            "page_ndcg_at_5": 0.70,
            "latency_ms_p95": 100.0,
        },
        "candidate": {
            "case_count": 192,
            "page_hit_at_5": 169 / 192,
            "page_ndcg_at_5": 0.76,
            "latency_ms_p95": 105.0,
        },
        "paired_outcomes": {
            "case_count": 192,
            "both_hit": 154,
            "candidate_only_hit": 15,
            "baseline_only_hit": 0,
            "both_miss": 23,
            "baseline_misses": 38,
            "candidate_misses": 23,
        },
        "company_macro": {},
        "page_hit_at_5_cluster_interval": {
            "lower_95": 0.04,
            "estimate": 15 / 192,
            "upper_95": 0.12,
        },
        "page_ndcg_at_5_cluster_interval": {
            "lower_95": 0.03,
            "estimate": 0.06,
            "upper_95": 0.10,
        },
        "p95_latency_multiplier": 1.05,
        "gate_checks": {"minimum_hit_delta": True, "p95_latency_within_budget": True},
        "claim_boundary": ["Known-report page localization only; not answer accuracy."],
    }


def _payload(evidence: dict[str, object]) -> bytes:
    return (json.dumps(evidence, sort_keys=True) + "\n").encode()


def _reference(payload: bytes) -> ExternalAggregateEvidenceReference:
    return ExternalAggregateEvidenceReference.model_validate(
        {
            "schema_version": "evalops.external-evidence-reference/1.0",
            "evidence_id": "rag-r5",
            "source_repository": "https://example.test/rag",
            "source_sha": "a" * 40,
            "source_ci": {
                "run_id": 123,
                "url": "https://example.test/actions/123",
                "status": "completed",
                "conclusion": "success",
            },
            "artifact_path": "evidence.json",
            "artifact_sha256": hashlib.sha256(payload).hexdigest(),
            "artifact_schema": "uda_finance_r5_public_v1",
            "evidence_scope": "fresh_known_report_page_localization",
            "expected_case_count": 192,
            "expected_decision": "PROMOTED_FINANCE_KNOWN_REPORT_DEFAULT",
            "producing_code_sha": "c" * 40,
            "protocol_sha256": "b" * 64,
            "allowed_claims": ("bounded aggregate claim",),
            "forbidden_claims": ("answer accuracy",),
        }
    )


def test_verifies_aggregate_bytes_but_keeps_formal_case_results_blocked() -> None:
    payload = _payload(_evidence())

    result = verify_external_aggregate_evidence(_reference(payload), payload)

    assert result["status"] == "AGGREGATE_EVIDENCE_VERIFIED"
    assert result["private_or_per_case_payload_present"] is False
    assert result["formal_case_result_status"] == "INPUT_REQUIRED"
    assert result["formal_ab_status"] == "NOT_RUN_BY_EVALOPS"
    assert result["formal_quality_claim_allowed"] is False
    assert result["production_ready"] is False


def test_rejects_digest_mismatch() -> None:
    payload = _payload(_evidence())

    with pytest.raises(ExternalEvidenceError, match="SHA-256 mismatch"):
        verify_external_aggregate_evidence(_reference(payload), payload + b" ")


def test_rejects_private_or_per_case_payload() -> None:
    evidence = _evidence()
    evidence["cases"] = [{"question": "private"}]
    payload = _payload(evidence)

    with pytest.raises(ExternalEvidenceError, match="private/per-case payload"):
        verify_external_aggregate_evidence(_reference(payload), payload)


def test_rejects_case_count_drift_and_failed_source_gate() -> None:
    evidence = _evidence()
    evidence["candidate"] = {"case_count": 191}
    payload = _payload(evidence)
    with pytest.raises(ExternalEvidenceError, match="case-count mismatch"):
        verify_external_aggregate_evidence(_reference(payload), payload)

    evidence = _evidence()
    evidence["gate_checks"] = {"minimum_hit_delta": False}
    payload = _payload(evidence)
    with pytest.raises(ExternalEvidenceError, match="failed source gate"):
        verify_external_aggregate_evidence(_reference(payload), payload)


def test_rejects_internally_inconsistent_paired_counts() -> None:
    evidence = _evidence()
    paired = evidence["paired_outcomes"]
    assert isinstance(paired, dict)
    paired["both_miss"] = 22
    payload = _payload(evidence)

    with pytest.raises(ExternalEvidenceError, match="do not sum"):
        verify_external_aggregate_evidence(_reference(payload), payload)


def test_tracked_rag_r5_record_preserves_source_identity_and_fail_closed_boundary() -> None:
    project_root = Path(__file__).parents[3]
    reference = json.loads(
        (project_root / "benchmarks/external_evidence/rag_r5_reference.json").read_text(
            encoding="utf-8"
        )
    )
    result = json.loads(
        (project_root / "docs/results/rag_r5_external_evidence/verification.json").read_text(
            encoding="utf-8"
        )
    )

    assert result["source"]["sha"] == reference["source_sha"]
    assert result["source"]["artifact_sha256"] == reference["artifact_sha256"]
    assert result["source"]["ci"] == reference["source_ci"]
    assert result["status"] == "AGGREGATE_EVIDENCE_VERIFIED"
    assert result["formal_case_result_status"] == "INPUT_REQUIRED"
    assert result["formal_quality_claim_allowed"] is False
    assert result["production_ready"] is False
