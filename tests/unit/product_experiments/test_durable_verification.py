import hashlib

import pytest

from app.product_experiments.durable_report import build_durable_report
from app.product_experiments.durable_verification import verify_durable_report
from app.product_experiments.export_schemas import PublicDurableReport
from app.product_experiments.export_service import encode_report
from app.product_experiments.public_summary import project_public_summary
from app.product_experiments.runner import ProductExperimentResult
from app.runs.idempotency import canonical_request_hash
from tests.unit.product_experiments.test_durable_report import durable_evidence as durable_evidence
from tests.unit.product_experiments.test_submission import submission_inputs as submission_inputs


@pytest.mark.parametrize("submission_inputs", ["QA", "AGENT_TOOL_USE"], indirect=True)
async def test_private_report_requires_raw_source_for_independent_recomputation(durable_evidence):
    snapshot, raw = durable_evidence
    report = build_durable_report(snapshot=snapshot, raw_dataset=raw)
    payload = encode_report(report)
    digest = hashlib.sha256(payload).hexdigest()
    incomplete = verify_durable_report(payload, expected_sha256=digest)
    assert incomplete.verification_scope == "PRIVATE_SOURCE_REQUIRED"
    verified = verify_durable_report(payload, raw_dataset=raw, expected_sha256=digest)
    assert verified.verification_scope == "PRIVATE_RECOMPUTED"
    assert verified.report_sha256 == digest
    assert verified.quality_status == "INSUFFICIENT_EVIDENCE"
    with pytest.raises(ValueError):
        verify_durable_report(payload, raw_dataset=raw, expected_sha256="0" * 64)


async def test_rehashed_quality_status_tampering_is_not_independent_verification(durable_evidence):
    snapshot, raw = durable_evidence
    report = build_durable_report(snapshot=snapshot, raw_dataset=raw)
    report["result"]["status"] = "DEMO_PASS"
    report.pop("content_sha256")
    report["content_sha256"] = canonical_request_hash(report)
    with pytest.raises(ValueError, match="report_recomputation_mismatch"):
        verify_durable_report(encode_report(report), raw_dataset=raw)


async def test_public_report_is_only_a_projection_even_if_raw_source_is_supplied(durable_evidence):
    snapshot, raw = durable_evidence
    private = build_durable_report(snapshot=snapshot, raw_dataset=raw)
    result = ProductExperimentResult.model_validate_json(encode_report(private["result"]))
    public = PublicDurableReport(
        private_report_sha256=hashlib.sha256(encode_report(private)).hexdigest(),
        result_snapshot_sha256=snapshot["content_sha256"],
        summary=project_public_summary(
            result,
            private_result_sha256=hashlib.sha256(encode_report(private["result"])).hexdigest(),
        ),
    )
    verification = verify_durable_report(public.model_dump_json().encode(), raw_dataset=raw)
    assert verification.verification_scope == "PUBLIC_PROJECTION_ONLY"
    assert verification.formal_quality_claim_allowed is False
