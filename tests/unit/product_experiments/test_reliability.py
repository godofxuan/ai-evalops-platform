"""Synthetic unit evidence only: no database, worker process or model acceptance claim."""

import hashlib
import json
from copy import deepcopy
from typing import Any
from uuid import uuid4

import pytest

from app.evaluators.product import ProductAgentEvaluator, ProductQAEvaluator
from app.product_experiments import reliability
from app.product_experiments.durable_report import build_durable_report
from app.product_experiments.durable_verification import verify_durable_report
from app.product_experiments.evaluators import registered_evaluators
from app.product_experiments.export_schemas import PublicDurableReport
from app.product_experiments.export_service import encode_report
from app.product_experiments.public_summary import project_public_summary
from app.product_experiments.reliability import (
    ReliabilityPlan,
    build_reliability_report,
    render_reliability_html,
    verify_reliability_report,
)
from app.product_experiments.runner import (
    ProductExperimentResult,
    ProviderResult,
    parse_product_dataset,
    score_product_case,
)
from app.runs.idempotency import canonical_request_hash
from tests.unit.product_experiments.test_durable_report import durable_evidence as durable_evidence
from tests.unit.product_experiments.test_submission import submission_inputs as submission_inputs


def _rehash(value: dict[str, Any]) -> None:
    value.pop("content_sha256", None)
    value["content_sha256"] = canonical_request_hash(value)


def _plan(snapshot: dict[str, Any], *, trials: int = 2, **changes: Any) -> ReliabilityPlan:
    return ReliabilityPlan.model_validate_json(
        json.dumps(
            {
                "panel_id": str(uuid4()),
                "tenant_id": snapshot["tenant_id"],
                "trial_count": trials,
                "request": snapshot["input_snapshot"]["request"],
                "evalops_sha": snapshot["input_snapshot"]["evalops_sha"],
                "environment_sha256": "a" * 64,
                "sampling_kind": "SYNTHETIC",
                **changes,
            }
        )
    )


def _trial(snapshot: dict[str, Any], plan: ReliabilityPlan, trial: int) -> dict[str, Any]:
    result = deepcopy(snapshot)
    result["experiment_id"] = str(uuid4())
    result["input_snapshot"]["request"] = plan.trial_request(trial).model_dump(mode="json")
    for arm in result["arms"].values():
        arm["run_id"] = str(uuid4())
        for row in arm["jobs"]:
            row["run_id"] = arm["run_id"]
            for key in ("job_id", "result_id", "accepted_attempt_id"):
                row[key] = str(uuid4())
    return result


def _payload(snapshot: dict[str, Any], raw: bytes) -> bytes:
    _rehash(snapshot["input_snapshot"])
    snapshot["request_sha256"] = canonical_request_hash(snapshot["input_snapshot"]["request"])
    _rehash(snapshot)
    result = encode_report(build_durable_report(snapshot=snapshot, raw_dataset=raw))
    assert verify_durable_report(result, raw_dataset=raw).verification_scope == "PRIVATE_RECOMPUTED"
    return result


def _mark_unsuccessful(snapshot: dict[str, Any], raw: bytes, case_index: int) -> None:
    row = snapshot["arms"]["candidate"]["jobs"][case_index]
    metrics = row["metrics"]
    metrics["product_observation"]["answer"] = "synthetic incorrect answer"
    case = parse_product_dataset(raw, expected_sha256=hashlib.sha256(raw).hexdigest())[case_index]
    metrics["product_scores"] = score_product_case(
        case,
        ProviderResult.model_validate_json(json.dumps(metrics["product_observation"])),
        evaluators=registered_evaluators(
            ProductQAEvaluator.evaluator_names
            if metrics["product_task_type"] == "QA"
            else ProductAgentEvaluator.evaluator_names
        ),
    )


@pytest.mark.parametrize("submission_inputs", ["QA", "AGENT_TOOL_USE"], indirect=True)
async def test_complete_panel_uses_cases_and_trials_not_retry_attempts(durable_evidence) -> None:
    snapshot, raw = durable_evidence
    plan = _plan(snapshot, trials=3)
    reports = []
    for trial, misses in ((1, (1,)), (2, ()), (3, (0, 1))):
        item = _trial(snapshot, plan, trial)
        for case in misses:
            _mark_unsuccessful(item, raw, case)
        reports.append((trial, _payload(item, raw)))
    result = build_reliability_report(plan=plan, raw_dataset=raw, reports=reports)
    assert result["status"] == "COMPLETE_DESCRIPTIVE_PANEL"
    assert result["trial_count"] == 3 and result["case_count"] == 2
    baseline = result["arms"]["baseline"]["summary"]
    candidate = result["arms"]["candidate"]["summary"]
    assert baseline["mean_task_success"] == baseline["empirical_all_at_k"] == 1.0
    assert candidate["mean_task_success"] == 0.5
    assert candidate["empirical_any_at_k"] == 1.0
    assert candidate["empirical_all_at_k"] == 0.0
    assert candidate["expected_cells"] == 6
    assert candidate["known_attempts"] == 12 and candidate["known_retries"] == 6
    assert candidate["complete_case_success_count_histogram"] == {"0": 0, "1": 1, "2": 1, "3": 0}
    assert candidate["accepted_observation_cost_usd"] == pytest.approx(0.06)
    assert candidate["total_execution_cost_usd"] is None
    assert candidate["accepted_observation_latency_p95_ms"] == 10.0
    assert result["statistical_independence"] == "NOT_ATTESTED"
    assert result["preregistration"] == "CLIENT_PLAN_BOUND_ONLY"
    assert result["formal_quality_claim_allowed"] is False
    assert result["production_ready"] is False
    assert {pin["reported_quality_status"] for pin in result["trial_reports"]} == {
        "INSUFFICIENT_EVIDENCE"
    }
    assert "private answer" not in json.dumps(result)
    assert render_reliability_html(result) == render_reliability_html(
        json.loads(encode_report(result))
    )
    verify_reliability_report(
        encode_report(result), plan=plan, raw_dataset=raw, reports=list(reversed(reports))
    )


@pytest.mark.parametrize("supplied", [0, 1])
async def test_missing_trials_remain_in_denominator_and_block_complete_metrics(
    durable_evidence, supplied
) -> None:
    snapshot, raw = durable_evidence
    plan = _plan(snapshot)
    reports = [(1, _payload(_trial(snapshot, plan, 1), raw))] if supplied else []
    result = build_reliability_report(plan=plan, raw_dataset=raw, reports=reports)
    summary = result["arms"]["candidate"]["summary"]
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert summary["expected_cells"] == 4
    assert summary["counts"]["MISSING_TRIAL"] == 4 - 2 * supplied
    assert summary["coverage"] == 0.5 * supplied
    assert summary["mean_task_success"] is None
    assert summary["empirical_any_at_k"] is None and summary["empirical_all_at_k"] is None
    assert len(result["arms"]["candidate"]["cells"]) == 4


@pytest.mark.parametrize("state", ["failed", "cancelled", "unknown"])
async def test_non_observed_cells_are_not_converted_to_success_or_silently_dropped(
    durable_evidence, state
) -> None:
    snapshot, raw = durable_evidence
    plan = _plan(snapshot)
    first, second = (_trial(snapshot, plan, index) for index in (1, 2))
    row = second["arms"]["candidate"]["jobs"][0]
    if state == "unknown":
        row["metrics"]["product_observation"]["cost_usd"] = None
        row["metrics"].update(
            product_status="INSUFFICIENT_EVIDENCE",
            product_missing=["MISSING_COST_MEASUREMENT"],
            product_scores={},
        )
    else:
        row.update(
            job_status=state,
            metrics=None,
            accepted_attempt_id=None,
            accepted_attempt_number=None,
            accepted_started_at=None,
            accepted_finished_at=None,
            result_id=None,
            error_code="synthetic_execution_failure",
        )
        second["arms"]["candidate"]["run_status"] = "partially_succeeded"
    reports = [(1, _payload(first, raw)), (2, _payload(second, raw))]
    result = build_reliability_report(plan=plan, raw_dataset=raw, reports=reports)
    summary = result["arms"]["candidate"]["summary"]
    status = {"failed": "EXECUTION_FAILED", "cancelled": "CANCELLED", "unknown": "UNKNOWN"}[state]
    assert summary["counts"][status] == 1 and summary["counts"]["OBSERVED"] == 3
    assert summary["expected_cells"] == 4 and summary["coverage"] == 0.75
    assert summary["observed_success_rate"] == 1.0
    assert summary["mean_task_success"] is None and summary["empirical_all_at_k"] is None
    assert result["arms"]["candidate"]["cells"][2]["success"] is None


@pytest.mark.parametrize("kind", ["execution", "run", "job", "result", "attempt"])
async def test_cross_trial_identity_reuse_is_rejected_after_private_recomputation(
    durable_evidence, kind
) -> None:
    snapshot, raw = durable_evidence
    plan = _plan(snapshot)
    first, second = (_trial(snapshot, plan, index) for index in (1, 2))
    if kind == "execution":
        second["experiment_id"] = first["experiment_id"]
    elif kind == "run":
        reused = first["arms"]["candidate"]["run_id"]
        second["arms"]["candidate"]["run_id"] = reused
        for row in second["arms"]["candidate"]["jobs"]:
            row["run_id"] = reused
    else:
        key = {"job": "job_id", "result": "result_id", "attempt": "accepted_attempt_id"}[kind]
        second["arms"]["candidate"]["jobs"][0][key] = first["arms"]["candidate"]["jobs"][0][key]
    reports = [(1, _payload(first, raw)), (2, _payload(second, raw))]
    with pytest.raises(ValueError, match="panel_reused_execution_identity"):
        build_reliability_report(plan=plan, raw_dataset=raw, reports=reports)


async def test_duplicate_trial_is_rejected(durable_evidence) -> None:
    snapshot, raw = durable_evidence
    plan = _plan(snapshot)
    evidence = _payload(_trial(snapshot, plan, 1), raw)
    with pytest.raises(ValueError, match="panel_duplicate_trial"):
        build_reliability_report(plan=plan, raw_dataset=raw, reports=[(1, evidence), (1, evidence)])


@pytest.mark.parametrize("change", ["tenant", "code", "request", "component"])
async def test_valid_private_reports_must_match_plan_and_observed_components(
    durable_evidence, change
) -> None:
    snapshot, raw = durable_evidence
    plan = _plan(snapshot)
    first, second = (_trial(snapshot, plan, index) for index in (1, 2))
    if change == "tenant":
        second["tenant_id"] = str(uuid4())
    elif change == "code":
        second["input_snapshot"]["evalops_sha"] = "f" * 40
    elif change == "request":
        second["input_snapshot"]["request"]["experiment_id"] = "unplanned-retrospective-selection"
    else:
        second["input_snapshot"]["components"]["candidate"]["target_config_sha256"] = "f" * 64
        second["arms"]["candidate"]["target_config_sha256"] = "f" * 64
    reports = [(1, _payload(first, raw)), (2, _payload(second, raw))]
    code = "panel_component_drift" if change == "component" else "panel_plan_binding_mismatch"
    with pytest.raises(ValueError, match=code):
        build_reliability_report(plan=plan, raw_dataset=raw, reports=reports)


async def test_public_projection_cannot_supply_panel_observations(durable_evidence) -> None:
    snapshot, raw = durable_evidence
    plan = _plan(snapshot)
    payload = _payload(_trial(snapshot, plan, 1), raw)
    private = json.loads(payload)
    result = ProductExperimentResult.model_validate_json(encode_report(private["result"]))
    public = (
        PublicDurableReport(
            private_report_sha256=hashlib.sha256(payload).hexdigest(),
            result_snapshot_sha256=private["result_snapshot_sha256"],
            summary=project_public_summary(
                result,
                private_result_sha256=hashlib.sha256(encode_report(private["result"])).hexdigest(),
            ),
        )
        .model_dump_json()
        .encode()
    )
    assert (
        verify_durable_report(public, raw_dataset=raw).verification_scope
        == "PUBLIC_PROJECTION_ONLY"
    )
    with pytest.raises(ValueError, match="panel_private_recomputation_required"):
        build_reliability_report(plan=plan, raw_dataset=raw, reports=[(1, public)])


async def test_rehashing_forged_panel_summary_does_not_make_it_reproducible(
    durable_evidence,
) -> None:
    snapshot, raw = durable_evidence
    plan = _plan(snapshot)
    reports = [(index, _payload(_trial(snapshot, plan, index), raw)) for index in (1, 2)]
    result = build_reliability_report(plan=plan, raw_dataset=raw, reports=reports)
    result["arms"]["candidate"]["summary"]["mean_task_success"] = 0.123
    _rehash(result)
    with pytest.raises(ValueError, match="panel_report_recomputation_mismatch"):
        verify_reliability_report(
            encode_report(result), plan=plan, raw_dataset=raw, reports=reports
        )


async def test_html_projection_escapes_case_identifiers_and_never_interprets_markup(
    durable_evidence,
) -> None:
    snapshot, raw = durable_evidence
    report = build_reliability_report(plan=_plan(snapshot), raw_dataset=raw, reports=[])
    report["arms"]["candidate"]["cells"][0]["case_id"] = '</pre><script>alert("CANARY")</script>'
    rendered = render_reliability_html(report)
    assert "<script>" not in rendered
    assert "&lt;/pre&gt;&lt;script&gt;" in rendered
    assert "CANARY" in rendered


async def test_panel_nonce_changes_identity_but_reloading_plan_preserves_resume_keys(
    durable_evidence,
) -> None:
    snapshot, _ = durable_evidence
    first, second = _plan(snapshot), _plan(snapshot)
    restored = ReliabilityPlan.model_validate_json(first.model_dump_json())
    assert first.plan_sha256 != second.plan_sha256
    assert restored.plan_sha256 == first.plan_sha256
    assert restored.idempotency_key(1) == first.idempotency_key(1)
    assert first.idempotency_key(1) != first.idempotency_key(2)
    assert first.trial_request(1).experiment_id == first.idempotency_key(1)


@pytest.mark.parametrize("trial", [0, -1, 3, True, 1.0, "1"])
async def test_trial_identity_requires_exact_in_range_integer(durable_evidence, trial) -> None:
    snapshot, _ = durable_evidence
    with pytest.raises(ValueError, match="invalid_trial_index"):
        _plan(snapshot).trial_request(trial)


@pytest.mark.parametrize("trials", [1, 11, True])
async def test_panel_trial_budget_is_strict(durable_evidence, trials) -> None:
    snapshot, _ = durable_evidence
    with pytest.raises(ValueError):
        _plan(snapshot, trials=trials)


async def test_panel_dataset_and_attempt_budgets_are_checked_before_report_reads(
    durable_evidence, monkeypatch
) -> None:
    snapshot, raw = durable_evidence
    plan = _plan(snapshot)
    with pytest.raises(ValueError, match="invalid_panel_dataset_size"):
        plan.validate_dataset(b"")
    with pytest.raises(ValueError):
        plan.validate_dataset(raw + b" ")
    values = deepcopy(snapshot["input_snapshot"]["request"])
    values["max_total_attempts"] = 200_000
    with pytest.raises(ValueError, match="panel_attempt_limit"):
        _plan(snapshot, request=values)
    values["max_total_attempts"] = 1
    with pytest.raises(ValueError, match="panel_attempt_budget_cannot_cover_cases"):
        _plan(snapshot, request=values).validate_dataset(raw)
    monkeypatch.setattr(reliability, "MAX_PANEL_CELLS", 3)
    with pytest.raises(ValueError, match="panel_case_limit"):
        build_reliability_report(plan=plan, raw_dataset=raw, reports=[])


async def test_report_count_and_output_size_are_bounded(durable_evidence, monkeypatch) -> None:
    snapshot, raw = durable_evidence
    plan = _plan(snapshot)
    with pytest.raises(ValueError, match="panel_too_many_reports"):
        build_reliability_report(plan=plan, raw_dataset=raw, reports=[(1, b"")] * 3)
    monkeypatch.setattr(reliability, "MAX_PANEL_REPORT_BYTES", 100)
    with pytest.raises(ValueError, match="panel_report_byte_limit"):
        build_reliability_report(plan=plan, raw_dataset=raw, reports=[])
    with pytest.raises(ValueError, match="panel_report_byte_limit"):
        verify_reliability_report(b"x" * 101, plan=plan, raw_dataset=raw, reports=[])
