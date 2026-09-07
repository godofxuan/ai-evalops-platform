"""Reachable local/worker contract regressions; all target contents are synthetic."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.domain.evaluation import EvaluationCase, TargetResult
from app.evaluators.product import ProductAgentEvaluator, ProductQAEvaluator
from app.product_experiments.runner import (
    run_experiment,
)
from app.targets.base import TargetExecutionError, TargetInvalidResponseError
from scripts.verify_product_experiment import verify_manifest
from tests.unit.product_experiments.test_runner import _agent_experiment, _experiment


@pytest.mark.parametrize("task", ["QA", "AGENT_TOOL_USE"])
def test_oversized_fixture_answer_exports_failed_case_not_input_error(tmp_path: Path, task):
    path = _experiment(tmp_path) if task == "QA" else _agent_experiment(tmp_path)
    cases = json.loads((tmp_path / "cases.json").read_bytes())[:2]
    bad_id = cases[0]["case_id"]
    cases[0]["metadata"]["fixture_profiles"]["candidate"]["answer"] = "x" * 100001
    raw = json.dumps(cases).encode()
    (tmp_path / "cases.json").write_bytes(raw)
    spec = json.loads(path.read_bytes())
    spec["dataset"]["sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(spec), encoding="utf-8")
    output = tmp_path / "failed-bundle"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.run_product_experiment",
            "--spec",
            str(path),
            "--output-dir",
            str(output),
            "--export-mode",
            "private",
            "--evalops-sha",
            "a" * 40,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 3, result.stderr
    report = json.loads((output / "result.json").read_bytes())
    assert report["status"] == "EXECUTION_FAILED"
    assert report["case_count"] == 2
    assert len(report["observations"]["baseline"]) == 2
    assert len(report["observations"]["candidate"]) == 1
    assert report["execution_errors"] == [
        {
            "arm": "candidate",
            "case_id": bad_id,
            "error_code": "target_answer_too_long",
            "retryable": False,
            "upstream_status_code": None,
        }
    ]
    assert "x" * 1000 not in (output / "result.json").read_text(encoding="utf-8")
    assert verify_manifest(output / "manifest.json")["status"] == "EXECUTION_FAILED"


async def test_conflicting_terminal_cannot_pass_full_local_gate(tmp_path: Path):
    path = _agent_experiment(tmp_path)
    cases = json.loads((tmp_path / "cases.json").read_bytes())
    for case in cases:
        candidate = case["metadata"]["fixture_profiles"]["candidate"]
        candidate["terminal_state"] = "failed"
        candidate["source_terminal_state"] = "answer"
    raw = json.dumps(cases).encode()
    (tmp_path / "cases.json").write_bytes(raw)
    spec = json.loads(path.read_bytes())
    spec["dataset"]["sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(spec), encoding="utf-8")
    report = await run_experiment(path, evalops_sha="a" * 40)
    assert report.status == "EXECUTION_FAILED"
    assert report.case_count == 120
    assert len(report.execution_errors) == 120
    assert report.observations["candidate"] == {}
    assert all(not failure.retryable for failure in report.execution_errors)


async def test_fixture_missing_terminal_is_insufficient_not_completed(tmp_path: Path):
    path = _agent_experiment(tmp_path)
    cases = json.loads((tmp_path / "cases.json").read_bytes())
    for case in cases:
        case["metadata"]["fixture_profiles"]["candidate"].pop("terminal_state")
    raw = json.dumps(cases).encode()
    (tmp_path / "cases.json").write_bytes(raw)
    spec = json.loads(path.read_bytes())
    spec["dataset"]["sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(spec), encoding="utf-8")
    report = await run_experiment(path, evalops_sha="a" * 40)
    assert report.status == "INSUFFICIENT_EVIDENCE"
    assert all(
        "terminal_state" in item.missing_fields
        for item in report.observations["candidate"].values()
    )


@pytest.mark.parametrize(
    "task,fault", [("QA", "answer"), ("AGENT_TOOL_USE", "answer"), ("AGENT_TOOL_USE", "terminal")]
)
async def test_local_real_http_invalid_observation_retains_failed_case(tmp_path: Path, task, fault):
    import httpx

    from tests.product_http_support import (
        FixtureResolver,
        LoopbackTargetService,
        LoopbackTargetTransport,
    )

    path = _experiment(tmp_path) if task == "QA" else _agent_experiment(tmp_path)
    cases = json.loads((tmp_path / "cases.json").read_bytes())[:2]
    raw = json.dumps(cases).encode()
    (tmp_path / "cases.json").write_bytes(raw)
    spec = json.loads(path.read_bytes())
    spec["dataset"]["sha256"] = hashlib.sha256(raw).hexdigest()
    spec["arms"][1]["provider"] = {
        "type": "http",
        "target_id": "candidate",
        "base_url": "https://rag.example.com",
        "endpoint": "/query",
    }
    path.write_text(json.dumps(spec), encoding="utf-8")

    def response(index):
        return {
            "answer": "x" * 100001 if fault == "answer" and index == 1 else "ok",
            "trace": {
                "cost_usd": 0.01,
                "tool_calls": [],
                "tool_error": False,
                "terminal_state": "failed" if fault == "terminal" and index == 1 else "completed",
                "source_terminal_state": "answer",
                "budget_exhausted": False,
            },
        }

    async with (
        LoopbackTargetService(response_for=response) as service,
        httpx.AsyncClient(transport=LoopbackTargetTransport(service.port)) as client,
    ):
        report = await run_experiment(
            path, evalops_sha="a" * 40, http_client=client, host_resolver=FixtureResolver()
        )
        assert len(service.requests) == 2
    assert report.status == "EXECUTION_FAILED"
    assert report.case_count == 2 and len(report.observations["candidate"]) == 1
    assert len(report.execution_errors) == 1
    assert report.execution_errors[0].error_code == (
        "target_answer_too_long" if fault == "answer" else "target_agent_terminal_invalid"
    )
    assert not report.execution_errors[0].retryable


def core_case(expected="completed"):
    return EvaluationCase(
        "contract",
        "q",
        "ok",
        {
            "evalops_product_case": {
                "case_id": "contract",
                "category": "basic",
                "prompt": "q",
                "reference_answer": "ok",
                "expected_citation_ids": ["gold"],
                "allowed_tools": [],
                "max_tool_calls": 0,
                "expected_terminal_state": expected,
            }
        },
    )


def target(answer="ok", **trace):
    return TargetResult(
        answer=answer,
        citations=({"source_id": "gold"},),
        sources=(),
        trace={
            "cost_usd": 0.01,
            "tool_calls": [],
            "tool_error": False,
            "terminal_state": "completed",
            "budget_exhausted": False,
            **trace,
        },
        token_usage=None,
        latency_ms=1,
    )


@pytest.mark.parametrize("task", [ProductQAEvaluator, ProductAgentEvaluator])
@pytest.mark.parametrize(
    "answer",
    ["ok", "x" * 99999, "x" * 100000, "字" * 100000],
    ids=["short", "99999", "100000", "unicode100000"],
)
def test_worker_answer_character_boundary_is_independent_of_bytes(task, answer):
    result = task(max_observation_bytes_per_case=1024 * 1024).evaluate(
        core_case(), target(answer), attempt_number=1
    )
    assert result.metrics["product_status"] == "OBSERVED"
    assert result.metrics["product_observation"]["answer"] == answer


@pytest.mark.parametrize("task", [ProductQAEvaluator, ProductAgentEvaluator])
def test_worker_rejects_character_overflow_before_success_metrics(task):
    with pytest.raises(TargetInvalidResponseError) as error:
        task(max_observation_bytes_per_case=1024 * 1024).evaluate(
            core_case(), target("x" * 100001), attempt_number=1
        )
    assert error.value.code == "target_answer_too_long"
    assert error.value.retryable is False


def test_unicode_answer_also_obeys_distinct_utf8_observation_budget():
    evaluator = ProductQAEvaluator(max_observation_bytes_per_case=200000)
    assert evaluator.evaluate(core_case(), target("x" * 100000), attempt_number=1)
    with pytest.raises(TargetExecutionError) as error:
        evaluator.evaluate(core_case(), target("字" * 100000), attempt_number=1)
    assert error.value.code == "experiment_observation_budget_exceeded"


TERMINALS = [
    ("answer", "completed"),
    ("refusal", "blocked"),
    ("permission_denied", "blocked"),
    ("budget_exhausted", "blocked"),
    ("partial", "failed"),
    ("tool_error", "failed"),
    ("agent_error", "failed"),
]


@pytest.mark.parametrize("source,coarse", TERMINALS)
@pytest.mark.parametrize("artifact", [False, True])
def test_agent_terminal_mapping_accepts_flat_and_artifact_without_inventing_reasons(
    source, coarse, artifact
):
    result = target(
        terminal_state=coarse,
        source_terminal_state=source,
        tool_error=source == "tool_error",
        budget_exhausted=source == "budget_exhausted",
    )
    if artifact:
        result = TargetResult(
            answer="ok",
            citations=(),
            sources=(),
            token_usage=None,
            latency_ms=1,
            trace={
                "schema_version": "agent-run-artifact/v1",
                "run_id": "r",
                "case_id": "contract",
                "session_id": "s",
                "framework": "fixture",
                "input": {"question": "q"},
                "output": {"answer": "ok"},
                "trajectory": [],
                "usage": {"currency": "USD", "cost": 0.01},
                "terminal": {"state": source},
            },
        )
    for expected in (coarse, "completed" if source == "answer" else source):
        metrics = (
            ProductAgentEvaluator().evaluate(core_case(expected), result, attempt_number=1).metrics
        )
        assert metrics["product_status"] == "OBSERVED"
        assert metrics["product_scores"]["agent_task_completion"] == 1
        assert metrics["product_scores"]["tool_budget_violation_rate"] == 0
        assert metrics["product_observation"]["source_terminal_state"] == source
        assert metrics["product_observation"]["terminal_state"] == coarse


@pytest.mark.parametrize(
    "coarse,source", [("failed", "answer"), ("blocked", "answer"), ("completed", "unknown")]
)
def test_conflicting_or_unknown_terminal_rejected_by_worker(coarse, source):
    with pytest.raises(TargetInvalidResponseError) as error:
        ProductAgentEvaluator().evaluate(
            core_case(),
            target(terminal_state=coarse, source_terminal_state=source),
            attempt_number=1,
        )
    assert error.value.code == "target_agent_terminal_invalid"
    assert not error.value.retryable


def test_legacy_terminal_without_source_is_valid_but_missing_terminal_is_insufficient():
    evaluator = ProductAgentEvaluator()
    result = evaluator.evaluate(core_case(), target(), attempt_number=1)
    assert result.metrics["product_scores"]["agent_task_completion"] == 1
    assert result.metrics["product_observation"]["source_terminal_state"] is None
    missing = target()
    missing.trace.pop("terminal_state")
    result = evaluator.evaluate(core_case(), missing, attempt_number=1)
    assert result.metrics["product_status"] == "INSUFFICIENT_EVIDENCE"
    assert result.metrics["product_scores"] == {}
