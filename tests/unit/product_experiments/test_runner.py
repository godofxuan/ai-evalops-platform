from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from app.product_experiments.runner import (
    DatasetIntegrityError,
    preflight_experiment,
    run_experiment,
)

CATEGORIES = (
    "basic",
    "semantic",
    "completeness",
    "conflicting_information",
    "high_level",
    "information_not_found",
)


@pytest.mark.parametrize("source", ["spec", "policy", "dataset"])
def test_preflight_rejects_duplicate_json_fields_before_execution(
    tmp_path: Path, source: str
) -> None:
    spec_path = _experiment(tmp_path)
    spec = json.loads(spec_path.read_bytes())
    if source == "spec":
        spec_path.write_bytes(b'{"scope":"FORMAL",' + spec_path.read_bytes()[1:])
    elif source == "policy":
        path = tmp_path / "policy.json"
        path.write_bytes(b'{"bootstrap_seed":0,' + path.read_bytes()[1:])
    else:
        path = tmp_path / spec["dataset"]["path"]
        payload = path.read_bytes()
        changed = payload.replace(b'"prompt":', b'"prompt":"hidden-first-value","prompt":', 1)
        assert changed != payload
        path.write_bytes(changed)
        spec["dataset"]["sha256"] = hashlib.sha256(changed).hexdigest()
        _write_json(spec_path, spec)
    with pytest.raises(ValueError, match="duplicate JSON"):
        preflight_experiment(spec_path)


@pytest.mark.asyncio
async def test_experiment_deadline_preserves_partial_observations(tmp_path: Path) -> None:
    path = _experiment(tmp_path)
    spec = json.loads(path.read_text(encoding="utf-8"))
    # Allow startup headroom under a concurrent full-suite run; the target never returns.
    spec["execution_timeout_seconds"] = 0.5
    spec["arms"][1]["provider"] = {
        "type": "http",
        "target_id": "candidate",
        "base_url": "https://rag.example.com",
        "endpoint": "/query",
    }
    _write_json(path, spec)
    closed = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()
        raise AssertionError("unreachable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await asyncio.wait_for(
            run_experiment(
                path, evalops_sha="e" * 40, http_client=client, host_resolver=PublicResolver()
            ),
            timeout=5,
        )
    assert result.status == "EXECUTION_FAILED"
    assert closed.is_set()
    observed_count = sum(len(rows) for rows in result.observations.values())
    assert 0 < observed_count < 240
    assert len(result.execution_errors) + observed_count == 240
    assert len({(error.arm, error.case_id) for error in result.execution_errors}) == len(
        result.execution_errors
    )
    assert {error.error_code for error in result.execution_errors} == {
        "experiment_deadline_exceeded"
    }
    assert result.case_comparisons == []
    assert set(result.category_diagnostics) == set(CATEGORIES)
    assert sum(item.case_count for item in result.category_diagnostics.values()) == 120
    assert all(item.undersampled_metrics for item in result.category_diagnostics.values())


@pytest.mark.parametrize("oversized", ["policy", "spec", "bootstrap"])
def test_preflight_rejects_unbounded_configuration_work(tmp_path: Path, oversized: str) -> None:
    path = _experiment(tmp_path)
    if oversized == "bootstrap":
        policy = json.loads((tmp_path / "policy.json").read_text())
        policy["bootstrap_resamples"] = 1_000_000
        _write_json(tmp_path / "policy.json", policy)
    else:
        selected = path if oversized == "spec" else tmp_path / "policy.json"
        selected.write_bytes(selected.read_bytes() + b" " * (1024 * 1024))
    with pytest.raises(ValueError, match="limit"):
        preflight_experiment(path)


@pytest.mark.asyncio
async def test_formal_label_cannot_qualify_fixture_evidence(tmp_path: Path) -> None:
    path = _experiment(tmp_path, scope="FORMAL")
    preflight = preflight_experiment(path)
    assert preflight["status"] == "INPUT_REQUIRED"
    assert "FORMAL_FIXTURE_NOT_ELIGIBLE" in {
        item["code"] for item in preflight["input_requirements"]
    }
    result = await run_experiment(path, evalops_sha="e" * 40)
    assert result.status == "INPUT_REQUIRED"
    assert result.arms == {} and result.observations == {}
    assert result.automated_assessment["status"] == "NOT_RUN"
    assert result.formal_quality_claim_allowed is False


@pytest.mark.asyncio
async def test_missing_cost_stays_unknown_and_blocks_cost_gate(tmp_path: Path) -> None:
    path = _experiment(tmp_path)
    spec = json.loads(path.read_text())
    spec["arms"][1]["provider"] = {
        "type": "http",
        "target_id": "candidate",
        "base_url": "https://rag.example.com",
        "endpoint": "/query",
    }
    _write_json(path, spec)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"answer": "observed", "usage": {"input_tokens": 100, "output_tokens": 10}},
                extensions={"network_stream": PublicPeer()},
            )
        )
    ) as client:
        result = await run_experiment(
            path, evalops_sha="e" * 40, http_client=client, host_resolver=PublicResolver()
        )
    assert result.observations["candidate"]["case-000"].cost_usd is None
    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert result.automated_assessment["status"] == "NOT_RUN"
    assert {item["code"] for item in result.input_requirements} == {"MISSING_COST_MEASUREMENT"}
    assert result.case_comparisons == []
    assert result.metric_diagnostics["reference_answer"].valid_pair_count == 120
    assert result.metric_diagnostics["reference_answer"].missing_pair_count == 0
    assert result.metric_diagnostics["cost_usd"].valid_pair_count == 0
    assert result.metric_diagnostics["cost_usd"].missing_pair_count == 120
    assert result.metric_diagnostics["reference_answer"].decision_scope == "DESCRIPTIVE_ONLY"


@pytest.mark.asyncio
@pytest.mark.parametrize("cost", [True, -1, "0.01", float("nan"), float("inf")])
async def test_invalid_reported_cost_is_a_response_error(tmp_path: Path, cost: object) -> None:
    path = _experiment(tmp_path)
    spec = json.loads(path.read_text())
    spec["arms"][1]["provider"] = {
        "type": "http",
        "target_id": "candidate",
        "base_url": "https://rag.example.com",
        "endpoint": "/query",
    }
    _write_json(path, spec)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=json.dumps({"answer": "observed", "trace": {"cost_usd": cost}}),
                extensions={"network_stream": PublicPeer()},
            )
        )
    ) as client:
        result = await run_experiment(
            path, evalops_sha="e" * 40, http_client=client, host_resolver=PublicResolver()
        )
    assert result.status == "EXECUTION_FAILED"
    assert {error.error_code for error in result.execution_errors} == {"target_cost_invalid"}


@pytest.mark.asyncio
async def test_invalid_agent_terminal_is_a_safe_response_error(tmp_path: Path) -> None:
    path = _agent_experiment(tmp_path)
    spec = json.loads(path.read_text())
    spec["arms"][1]["provider"] = {
        "type": "http",
        "target_id": "candidate",
        "base_url": "https://rag.example.com",
        "endpoint": "/query",
    }
    _write_json(path, spec)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "answer": "observed",
                    "trace": {
                        "cost_usd": 0.01,
                        "terminal_state": "PRIVATE-INVALID-TERMINAL",
                        "tool_calls": [],
                        "tool_error": False,
                        "budget_exhausted": False,
                    },
                },
                extensions={"network_stream": PublicPeer()},
            )
        )
    ) as client:
        result = await run_experiment(
            path, evalops_sha="e" * 40, http_client=client, host_resolver=PublicResolver()
        )
    assert {error.error_code for error in result.execution_errors} == {
        "target_agent_observation_invalid"
    }
    assert "PRIVATE-INVALID-TERMINAL" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_qa_trace_schema_is_not_interpreted_as_agent_artifact(tmp_path: Path) -> None:
    path = _experiment(tmp_path)
    spec = json.loads(path.read_text())
    spec["arms"][1]["provider"] = {
        "type": "http",
        "target_id": "candidate",
        "base_url": "https://rag.example.com",
        "endpoint": "/query",
    }
    _write_json(path, spec)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "answer": "observed",
                    "trace": {
                        "schema_version": "qa-telemetry/v1",
                        "cost_usd": 0.01,
                    },
                },
                extensions={"network_stream": PublicPeer()},
            )
        )
    ) as client:
        result = await run_experiment(
            path, evalops_sha="e" * 40, http_client=client, host_resolver=PublicResolver()
        )
    assert result.execution_errors == []
    assert len(result.case_comparisons) == 120


@pytest.mark.asyncio
async def test_execution_snapshot_binds_policy_without_reusing_execution(tmp_path: Path) -> None:
    path = _experiment(tmp_path)
    first = await run_experiment(path, evalops_sha="e" * 40)
    replay = await run_experiment(path, evalops_sha="e" * 40)
    assert first.input_snapshot is not None
    assert first.input_snapshot == replay.input_snapshot
    assert first.execution_id != replay.execution_id
    policy_path = tmp_path / "policy.json"
    before = policy_path.read_bytes()
    policy = json.loads(before)
    policy["bootstrap_seed"] += 1
    _write_json(policy_path, policy)
    changed = await run_experiment(path, evalops_sha="e" * 40)
    assert changed.input_snapshot is not None
    assert first.input_snapshot["policy_sha256"] == hashlib.sha256(before).hexdigest()
    assert first.input_snapshot["content_sha256"] != changed.input_snapshot["content_sha256"]
    assert first.input_snapshot["policy"]["bootstrap_seed"] != policy["bootstrap_seed"]


@pytest.mark.asyncio
async def test_explicit_zero_tool_cases_can_execute(tmp_path: Path) -> None:
    path = _agent_experiment(tmp_path)
    spec = json.loads(path.read_text())
    cases = json.loads((tmp_path / "cases.json").read_text())
    for case in cases:
        case["allowed_tools"] = []
        case["expected_tool_calls"] = []
        case["max_tool_calls"] = 0
        for fixture in case["metadata"]["fixture_profiles"].values():
            fixture["tool_calls"] = []
    spec["dataset"]["sha256"] = _write_json(tmp_path / "cases.json", cases)
    _write_json(path, spec)
    assert preflight_experiment(path)["status"] == "READY"
    result = await run_experiment(path, evalops_sha="e" * 40)
    assert result.status == "DEMO_PASS"
    assert result.case_comparisons[0].candidate_agent_metrics["policy_violation_rate"] == 0


@pytest.mark.parametrize("violation", ["missing_allowlist", "unexpected_tool", "over_budget"])
def test_agent_preflight_rejects_incomplete_or_contradictory_labels(
    tmp_path: Path, violation: str
) -> None:
    path = _agent_experiment(tmp_path)
    spec = json.loads(path.read_text())
    cases = json.loads((tmp_path / "cases.json").read_text())
    if violation == "missing_allowlist":
        del cases[0]["allowed_tools"]
    elif violation == "unexpected_tool":
        cases[0]["allowed_tools"] = []
    else:
        cases[0]["max_tool_calls"] = 0
    spec["dataset"]["sha256"] = _write_json(tmp_path / "cases.json", cases)
    _write_json(path, spec)
    with pytest.raises(DatasetIntegrityError):
        preflight_experiment(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("observed,expected_score", [("refusal", 1.0), ("budget_exhausted", 0.0)])
async def test_agent_expected_refusal_is_not_confused_with_other_stops(
    tmp_path: Path, observed: str, expected_score: float
) -> None:
    path = _agent_experiment(tmp_path)
    spec = json.loads(path.read_text())
    cases = json.loads((tmp_path / "cases.json").read_text())
    for case in cases:
        case.update(
            allowed_tools=[],
            expected_tool_calls=[],
            max_tool_calls=0,
            expected_terminal_state="refusal",
        )
        for label, fixture in case["metadata"]["fixture_profiles"].items():
            fixture.update(
                tool_calls=[],
                terminal_state="blocked",
                source_terminal_state="refusal" if label == "baseline" else observed,
            )
    spec["dataset"]["sha256"] = _write_json(tmp_path / "cases.json", cases)
    _write_json(path, spec)
    result = await run_experiment(path, evalops_sha="e" * 40)
    assert (
        result.case_comparisons[0].candidate_agent_metrics["agent_task_completion"]
        == expected_score
    )


@pytest.mark.asyncio
async def test_agent_without_citations_does_not_receive_a_fabricated_citation_score(
    tmp_path: Path,
) -> None:
    result = await run_experiment(_agent_experiment(tmp_path), evalops_sha="e" * 40)
    assert result.arms["candidate"].cases[0].citation_correctness is None
    assert result.case_comparisons[0].candidate_citation_correctness is None
    assert result.automated_assessment["metric_applicability"]["citation"] == "NOT_APPLICABLE"
    assert result.status == "DEMO_PASS"


@pytest.mark.asyncio
async def test_extra_invented_citations_reduce_precision_and_fail_gate(tmp_path: Path) -> None:
    path = _experiment(tmp_path)
    spec = json.loads(path.read_text())
    cases = json.loads((tmp_path / "cases.json").read_text())
    for case in cases:
        case["metadata"]["fixture_profiles"]["candidate"]["citations"].append(
            {"source_id": "invented"}
        )
    spec["dataset"]["sha256"] = _write_json(tmp_path / "cases.json", cases)
    _write_json(path, spec)
    result = await run_experiment(path, evalops_sha="e" * 40)
    assert result.arms["candidate"].cases[0].citation_recall == 1.0
    assert result.arms["candidate"].cases[0].citation_precision == 0.5
    assert result.status == "DEMO_FAIL"


@pytest.mark.asyncio
async def test_qa_without_citation_labels_is_blocked_before_execution(tmp_path: Path) -> None:
    path = _experiment(tmp_path)
    spec = json.loads(path.read_text())
    cases = json.loads((tmp_path / "cases.json").read_text())
    for case in cases:
        case["expected_citation_ids"] = []
    spec["dataset"]["sha256"] = _write_json(tmp_path / "cases.json", cases)
    _write_json(path, spec)
    result = await run_experiment(path, evalops_sha="e" * 40)
    assert result.status == "INPUT_REQUIRED"
    assert result.arms == {}
    assert result.observations == {}
    assert {item["code"] for item in result.input_requirements} == {"MISSING_CITATION_LABELS"}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,status", [("qualification", "DEMO_PASS"), ("both", "DEMO_FAIL")])
async def test_qualification_does_not_hide_parameter_regression(
    tmp_path: Path, mode: str, status: str
) -> None:
    path = _agent_experiment(tmp_path)
    spec = json.loads(path.read_text())
    spec["agent_comparison_policy"] = {"mode": mode}
    cases = json.loads((tmp_path / "cases.json").read_text())
    for index, case in enumerate(cases):
        case["metadata"]["fixture_profiles"]["baseline"]["tool_calls"] = case["expected_tool_calls"]
        if index < 6:
            case["metadata"]["fixture_profiles"]["candidate"]["tool_calls"] = [
                {"name": "search", "arguments": {"query": "wrong"}}
            ]
    spec["dataset"]["sha256"] = _write_json(tmp_path / "cases.json", cases)
    _write_json(path, spec)
    result = await run_experiment(path, evalops_sha="e" * 40)
    assert result.status == status
    assert result.agent_tool_use_assessment["qualification_status"] == "PASS"
    assert result.agent_tool_use_assessment["non_regression_status"] == "FAIL"


@pytest.mark.asyncio
async def test_http_pairs_have_balanced_reproducible_arm_order(tmp_path: Path) -> None:
    path = _experiment(tmp_path)
    spec = json.loads(path.read_text())
    spec["max_concurrency"] = 1
    for arm in spec["arms"]:
        arm["provider"] = {
            "type": "http",
            "target_id": arm["label"],
            "base_url": "https://rag.example.com",
            "endpoint": "/" + arm["label"],
        }
    _write_json(path, spec)
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        question = json.loads(request.content)["question"]
        calls.append((question, request.url.path))
        return httpx.Response(
            200,
            json={"answer": "observed", "trace": {"cost_usd": 0.01}},
            extensions={"network_stream": PublicPeer()},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await run_experiment(
            path, evalops_sha="e" * 40, http_client=client, host_resolver=PublicResolver()
        )
        first_calls = calls.copy()
        calls.clear()
        second = await run_experiment(
            path, evalops_sha="e" * 40, http_client=client, host_resolver=PublicResolver()
        )
    assert len(first_calls) == 240
    assert all(first_calls[index][0] == first_calls[index + 1][0] for index in range(0, 240, 2))
    assert sum(first_calls[index][1] == "/baseline" for index in range(0, 240, 2)) == 60
    assert first_calls == calls
    assert first.execution_schedule == second.execution_schedule
    assert len(first.execution_events) == 240


@pytest.mark.asyncio
async def test_total_observation_budget_stops_retaining_and_scoring_results(tmp_path: Path) -> None:
    path = _experiment(tmp_path)
    spec = json.loads(path.read_text())
    spec["max_observation_bytes"] = 1024
    _write_json(path, spec)
    result = await run_experiment(path, evalops_sha="e" * 40)
    assert result.status == "EXECUTION_FAILED"
    assert result.case_comparisons == []
    assert {error.error_code for error in result.execution_errors} == {
        "experiment_observation_budget_exceeded"
    }
    retained = sum(
        len(item.model_dump_json().encode())
        for arm in result.observations.values()
        for item in arm.values()
    )
    assert 0 < retained <= 1024


def test_preflight_rejects_a_case_over_the_individual_byte_budget(tmp_path: Path) -> None:
    path = _experiment(tmp_path)
    spec = json.loads(path.read_text())
    cases = json.loads((tmp_path / "cases.json").read_text())
    cases[0]["metadata"]["oversized"] = "x" * (1024 * 1024)
    spec["dataset"]["sha256"] = _write_json(tmp_path / "cases.json", cases)
    _write_json(path, spec)
    with pytest.raises(DatasetIntegrityError, match="case.*limit"):
        preflight_experiment(path)


@pytest.mark.asyncio
async def test_small_demo_is_insufficient_not_a_quality_failure(tmp_path: Path) -> None:
    path = _experiment(tmp_path)
    spec = json.loads(path.read_text())
    cases = json.loads((tmp_path / "cases.json").read_text())[:2]
    spec["dataset"]["sha256"] = _write_json(tmp_path / "cases.json", cases)
    _write_json(path, spec)
    result = await run_experiment(path, evalops_sha="e" * 40)
    assert result.automated_assessment["status"] == "INSUFFICIENT_EVIDENCE"
    assert result.status == "INSUFFICIENT_EVIDENCE"


class PublicResolver:
    async def resolve(self, hostname: str) -> tuple[str, ...]:
        return ("93.184.216.34",)


class PublicPeer:
    def get_extra_info(self, name: str) -> object:
        return ("93.184.216.34", 443) if name == "server_addr" else None


@pytest.mark.asyncio
async def test_http_agent_execution_preserves_tools_errors_and_terminal(tmp_path: Path) -> None:
    spec_path = _agent_experiment(tmp_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    for arm in spec["arms"]:
        arm["provider"] = {
            "type": "http",
            "target_id": arm["label"],
            "base_url": "https://rag.example.com",
            "endpoint": "/query",
        }
    _write_json(spec_path, spec)

    def handler(request: httpx.Request) -> httpx.Response:
        index = int(json.loads(request.content)["question"].split()[1].rstrip("?"))
        return httpx.Response(
            200,
            json={
                "answer": f"answer-{index}",
                "trace": {
                    "trace_id": request.headers["X-EvalOps-Job-ID"],
                    "cost_usd": 0.01,
                    "terminal_state": "completed",
                    "tool_error": True,
                    "budget_exhausted": True,
                    "tool_calls": [
                        {
                            "name": "search",
                            "arguments": {"query": f"item-{index}"},
                            "status": "error",
                        }
                    ],
                },
            },
            extensions={"network_stream": PublicPeer()},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await run_experiment(
            spec_path, evalops_sha="e" * 40, http_client=client, host_resolver=PublicResolver()
        )
    row = result.case_comparisons[0]
    assert row.candidate_agent_metrics["agent_task_completion"] == 1.0
    assert row.candidate_agent_metrics["tool_error_rate"] == 1.0
    assert row.candidate_agent_metrics["tool_budget_violation_rate"] == 0.0
    assert result.observations["candidate"]["case-000"].budget_exhausted is True
    assert row.candidate_tool_calls[0]["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,retryable", [(401, False), (429, True), (503, True)])
async def test_http_execution_failure_is_not_graded_as_a_tool_error(
    tmp_path: Path,
    status: int,
    retryable: bool,
) -> None:
    path = _experiment(tmp_path)
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec["arms"][1]["provider"] = {
        "type": "http",
        "target_id": "candidate",
        "base_url": "https://rag.example.com",
        "endpoint": "/query",
    }
    _write_json(path, spec)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, text="PRIVATE-UPSTREAM-MARKER", extensions={"network_stream": PublicPeer()}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await run_experiment(
            path, evalops_sha="e" * 40, http_client=client, host_resolver=PublicResolver()
        )

    assert result.status == "EXECUTION_FAILED"
    assert result.automated_assessment["status"] == "NOT_RUN"
    assert result.case_comparisons == []
    assert {error.error_code for error in result.execution_errors} == {f"target_http_{status}"}
    assert all(error.retryable is retryable for error in result.execution_errors)
    assert "PRIVATE-UPSTREAM-MARKER" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_new_execution_does_not_reuse_target_job_ids(tmp_path: Path) -> None:
    path = _experiment(tmp_path)
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec["arms"][1]["provider"] = {
        "type": "http",
        "target_id": "candidate",
        "base_url": "https://rag.example.com",
        "endpoint": "/query",
    }
    _write_json(path, spec)
    sent_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_ids.append(request.headers["X-EvalOps-Job-ID"])
        return httpx.Response(
            200,
            json={"answer": "observed", "trace": {"cost_usd": 0.01}},
            extensions={"network_stream": PublicPeer()},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await run_experiment(
            path, evalops_sha="e" * 40, http_client=client, host_resolver=PublicResolver()
        )
        second = await run_experiment(
            path, evalops_sha="e" * 40, http_client=client, host_resolver=PublicResolver()
        )
    assert sent_ids[0] != sent_ids[120]
    assert first.execution_id != second.execution_id


@pytest.mark.asyncio
async def test_missing_http_agent_trace_is_insufficient_not_a_quality_score(tmp_path: Path) -> None:
    path = _agent_experiment(tmp_path)
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec["arms"][1]["provider"] = {
        "type": "http",
        "target_id": "candidate",
        "base_url": "https://rag.example.com",
        "endpoint": "/query",
    }
    _write_json(path, spec)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"answer": "observed", "trace": {"cost_usd": 0.01}},
            extensions={"network_stream": PublicPeer()},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await run_experiment(
            path, evalops_sha="e" * 40, http_client=client, host_resolver=PublicResolver()
        )

    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert result.case_comparisons == []
    assert result.execution_errors == []
    assert {item["code"] for item in result.input_requirements} == {"MISSING_AGENT_OBSERVATION"}
    assert "tool_calls" in result.observations["candidate"]["case-000"].missing_fields


@pytest.mark.asyncio
async def test_existing_agent_artifact_is_projected_without_losing_tool_results(
    tmp_path: Path,
) -> None:
    path = _agent_experiment(tmp_path)
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec["arms"][1]["provider"] = {
        "type": "http",
        "target_id": "candidate",
        "base_url": "https://rag.example.com",
        "endpoint": "/query",
    }
    _write_json(path, spec)

    def handler(request: httpx.Request) -> httpx.Response:
        index = int(json.loads(request.content)["question"].split()[1].rstrip("?"))
        artifact = {
            "schema_version": "agent-run-artifact/v1",
            "run_id": "external-run",
            "case_id": f"case-{index:03d}",
            "session_id": f"session-{index}",
            "framework": "test",
            "input": {},
            "output": {"answer": f"answer-{index}"},
            "trajectory": [
                {
                    "event_id": "call",
                    "event_type": "tool_call",
                    "step_id": "s1",
                    "tool_name": "search",
                    "payload": {"arguments": {"query": f"item-{index}"}},
                },
                {
                    "event_id": "result",
                    "event_type": "tool_result",
                    "step_id": "s1",
                    "tool_name": "search",
                    "payload": {"success": False},
                },
            ],
            "usage": {"cost": 0.01, "currency": "USD"},
            "terminal": {"state": "answer"},
        }
        return httpx.Response(
            200,
            json={"answer": f"answer-{index}", "trace": artifact},
            extensions={"network_stream": PublicPeer()},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await run_experiment(
            path, evalops_sha="e" * 40, http_client=client, host_resolver=PublicResolver()
        )
    assert result.case_comparisons
    row = result.case_comparisons[0]
    assert row.candidate_agent_metrics["agent_task_completion"] == 1.0
    assert row.candidate_agent_metrics["tool_error_rate"] == 1.0
    assert row.candidate_tool_calls[0]["status"] == "error"
    observation = result.observations["candidate"]["case-000"]
    assert observation.source_terminal_state == "answer"
    assert len(observation.artifact_sha256) == 64


@pytest.mark.parametrize("oversized", [False, True])
def test_preflight_rejects_unusable_dataset_limits(tmp_path: Path, oversized: bool) -> None:
    path = _experiment(tmp_path)
    content = b" " * (10 * 1024 * 1024 + 1) if oversized else b"[]"
    (tmp_path / "cases.json").write_bytes(content)
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec["dataset"]["sha256"] = hashlib.sha256(content).hexdigest()
    _write_json(path, spec)
    with pytest.raises(DatasetIntegrityError, match="size limit|case count"):
        preflight_experiment(path)


@pytest.mark.asyncio
async def test_http_execution_keeps_pending_tasks_bounded(tmp_path: Path) -> None:
    path = _experiment(tmp_path)
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec["arms"][1]["provider"] = {
        "type": "http",
        "target_id": "candidate",
        "base_url": "https://rag.example.com",
        "endpoint": "/query",
    }
    _write_json(path, spec)
    pending: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pending.append(len(asyncio.all_tasks()))
        return httpx.Response(
            200,
            json={"answer": "observed", "trace": {"cost_usd": 0.01}},
            extensions={"network_stream": PublicPeer()},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await run_experiment(
            path, evalops_sha="e" * 40, http_client=client, host_resolver=PublicResolver()
        )
    assert len(pending) == 120
    # Allow resolver/pytest tasks as well as active cases, but not one task per input row.
    assert max(pending) <= spec["max_concurrency"] * 2 + 8


def _write_json(path: Path, value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    path.write_text(payload + "\n", encoding="utf-8", newline="\n")
    return hashlib.sha256((payload + "\n").encode()).hexdigest()


def _case(index: int) -> dict[str, object]:
    category = CATEGORIES[index % len(CATEGORIES)]
    answer = f"answer-{index}"
    citation_id = f"source-{index}"
    return {
        "case_id": f"case-{index:03d}",
        "category": category,
        "prompt": f"Question {index}?",
        "reference_answer": answer,
        "expected_citation_ids": [citation_id],
        "metadata": {
            "fixture_profiles": {
                "baseline": {
                    "answer": answer,
                    "citations": [{"source_id": citation_id}],
                    "latency_ms": 40,
                    "cost_usd": 0.01,
                    "trace_id": f"demo-baseline-{index:03d}",
                },
                "candidate": {
                    "answer": answer,
                    "citations": [{"source_id": citation_id}],
                    "latency_ms": 44,
                    "cost_usd": 0.011,
                    "trace_id": f"demo-candidate-{index:03d}",
                },
            }
        },
    }


def _experiment(tmp_path: Path, *, scope: str = "DEMO") -> Path:
    dataset_path = tmp_path / "cases.json"
    dataset_sha = _write_json(dataset_path, [_case(index) for index in range(120)])
    policy = {
        "schema_version": "formal-agent-quality-policy/1.0",
        "minimum_common_cases": 120,
        "minimum_cases_per_category": 20,
        "required_categories": list(CATEGORIES),
        "bootstrap_resamples": 200,
        "bootstrap_seed": 20260902,
        "task_success_ci_lower_min": 0,
        "citation_correctness_ci_lower_min": -0.02,
        "tool_error_rate_ci_upper_max": 0.02,
        "latency_p95_relative_delta_max": 0.25,
        "cost_mean_relative_delta_max": 0.25,
        "require_exact_case_set": True,
    }
    _write_json(tmp_path / "policy.json", policy)
    spec = {
        "schema_version": "evalops.experiment/1.0",
        "experiment_id": "paired-rag-demo-v1",
        "scope": scope,
        "dataset": {"path": "cases.json", "sha256": dataset_sha},
        "policy_path": "policy.json",
        "arms": [
            {
                "label": "baseline",
                "source_repository": "demo://baseline",
                "source_sha": "b" * 40,
                "provider": {"type": "fixture", "profile": "baseline"},
            },
            {
                "label": "candidate",
                "source_repository": "demo://candidate",
                "source_sha": "c" * 40,
                "provider": {"type": "fixture", "profile": "candidate"},
            },
        ],
        "evaluators": ["reference_answer", "citation_correctness", "tool_error_rate"],
        "max_concurrency": 8,
    }
    spec_path = tmp_path / "experiment.json"
    _write_json(spec_path, spec)
    return spec_path


def _agent_experiment(tmp_path: Path) -> Path:
    spec_path = _experiment(tmp_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    cases = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    for index, case in enumerate(cases):
        expected = {"name": "search", "arguments": {"query": f"item-{index}"}}
        case["expected_citation_ids"] = []
        case["expected_tool_calls"] = [expected]
        case["allowed_tools"] = ["search"]
        case["max_tool_calls"] = 1
        for label in ("baseline", "candidate"):
            fixture = case["metadata"]["fixture_profiles"][label]
            fixture["terminal_state"] = "completed"
            fixture["tool_calls"] = [expected]
        if index % 5 == 0:
            case["metadata"]["fixture_profiles"]["baseline"]["tool_calls"] = [
                {"name": "admin_delete", "arguments": {}, "status": "success"}
            ]
    spec["task_type"] = "AGENT_TOOL_USE"
    spec["evaluators"] = [
        "agent_task_completion",
        "tool_selection_accuracy",
        "tool_argument_validity",
        "policy_violation_rate",
        "tool_budget_violation_rate",
        "tool_error_rate",
    ]
    spec["dataset"]["sha256"] = _write_json(tmp_path / "cases.json", cases)
    _write_json(spec_path, spec)
    return spec_path


@pytest.mark.asyncio
async def test_demo_runs_120_paired_cases_and_preserves_claim_boundary(tmp_path: Path) -> None:
    result = await run_experiment(_experiment(tmp_path), evalops_sha="e" * 40)

    assert result.status == "DEMO_PASS"
    assert result.scope == "DEMO"
    assert result.case_count == 120
    assert result.automated_assessment["status"] == "PASS"
    assert result.automated_assessment["decision"]["formal_ab_eligible"] is False
    assert result.automated_assessment["decision_outcome"] == "INPUT_BLOCKED"
    assert result.human_review_status == "PENDING"
    assert result.formal_quality_claim_allowed is False
    assert result.production_ready is False
    assert result.source_identities["baseline"] == {
        "repository": "demo://baseline",
        "sha": "b" * 40,
        "provider_type": "fixture",
    }
    assert len(result.arms["baseline"].cases) == 120
    assert len(result.arms["candidate"].cases) == 120
    assert result.case_comparisons[0].baseline_trace_id == "demo-baseline-000"
    assert result.case_comparisons[0].candidate_trace_id == "demo-candidate-000"


@pytest.mark.asyncio
async def test_agent_demo_compares_tool_traces_and_gates_agent_metrics(tmp_path: Path) -> None:
    result = await run_experiment(_agent_experiment(tmp_path), evalops_sha="e" * 40)

    assert result.status == "DEMO_PASS"
    assert result.task_type == "AGENT_TOOL_USE"
    assert result.agent_tool_use_assessment is not None
    assert result.agent_tool_use_assessment["status"] == "PASS"
    first = result.case_comparisons[0]
    assert first.baseline_agent_metrics["policy_violation_rate"] == 1.0
    assert first.candidate_agent_metrics["policy_violation_rate"] == 0.0
    assert first.baseline_tool_calls[0]["name"] == "admin_delete"
    assert first.candidate_tool_calls[0]["name"] == "search"


@pytest.mark.asyncio
async def test_dataset_digest_mismatch_fails_before_provider_execution(tmp_path: Path) -> None:
    spec_path = _experiment(tmp_path)
    values = json.loads(spec_path.read_text(encoding="utf-8"))
    values["dataset"]["sha256"] = "0" * 64
    _write_json(spec_path, values)

    with pytest.raises(DatasetIntegrityError, match="dataset SHA-256 mismatch"):
        await run_experiment(spec_path, evalops_sha="e" * 40)


@pytest.mark.asyncio
async def test_missing_http_credential_returns_machine_actionable_input_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = _experiment(tmp_path, scope="FORMAL")
    values = json.loads(spec_path.read_text(encoding="utf-8"))
    values["arms"][1]["provider"] = {
        "type": "http",
        "target_id": "candidate-rag",
        "base_url": "https://rag.example.com",
        "endpoint": "/v1/query",
        "auth_env_var": "CANDIDATE_RAG_TOKEN",
    }
    _write_json(spec_path, values)
    monkeypatch.delenv("CANDIDATE_RAG_TOKEN", raising=False)

    result = await run_experiment(spec_path, evalops_sha="e" * 40)

    assert result.status == "INPUT_REQUIRED"
    assert {
        "arm": "candidate",
        "code": "MISSING_CREDENTIAL_ENV",
        "environment_variable": "CANDIDATE_RAG_TOKEN",
    } in result.input_requirements
    assert result.formal_quality_claim_allowed is False
