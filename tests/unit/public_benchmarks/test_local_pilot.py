from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.public_benchmarks.local_pilot import (
    digest,
    encoded,
    execute_plan,
    read_json,
    verify_run,
    write_plan,
)


def plan_path(tmp_path: Path, *, budget: int = 6000) -> Path:
    return write_plan(
        tmp_path / "input",
        rows=[
            {
                "benchmark": "public-test",
                "case_id": "case-1",
                "category": "test",
                "model": "qwen2.5:3b",
                "model_digest": "a" * 64,
                "context_byte_budget": budget,
                "request": {
                    "model": "qwen2.5:3b",
                    "stream": False,
                    "messages": [{"role": "user", "content": "public question"}],
                    "options": {"num_ctx": 8192, "num_predict": 512},
                },
            }
        ],
        metadata={"evidence_kind": "TEST_FIXTURE_NOT_MODEL_BENCHMARK"},
    )


def local_client(
    calls: list[str],
    *,
    fail: bool = False,
    remote_field: str | None = None,
    http_failure: int | None = None,
) -> httpx.Client:
    """HTTP-boundary fixture only: it never measures a real Qwen model."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "127.0.0.1"
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test"})
        if request.url.path == "/api/tags":
            model = {"name": "qwen2.5:3b", "digest": "a" * 64}
            if remote_field is not None:
                model[remote_field] = "remote-fixture-not-a-real-service"
            return httpx.Response(200, json={"models": [model]})
        calls.append(request.url.path)
        if http_failure is not None:
            return httpx.Response(
                http_failure,
                headers={"x-private": "DO-NOT-RECORD-HEADER"},
                text="DO-NOT-RECORD-ERROR-BODY",
            )
        if fail:
            raise httpx.ReadTimeout("test timeout")
        assert json.loads(request.content)["messages"][0]["content"] == "public question"
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:3b",
                "done": True,
                "done_reason": "stop",
                "message": {"content": "[]"},
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_execute_persist_verify_and_resume_does_not_recall(tmp_path: Path) -> None:
    path = plan_path(tmp_path)
    calls: list[str] = []
    with local_client(calls) as client:
        result = execute_plan(path, tmp_path / "run", client=client)
        resumed = execute_plan(path, tmp_path / "run", client=client)
    assert result["statuses"] == {"RESPONDED": 1}
    assert result["new_target_calls"] == 1
    assert resumed["new_target_calls"] == 0
    assert calls == ["/api/chat"]
    assert verify_run(tmp_path / "run")["complete"] is True


def test_approved_gemma_executes_persists_and_verifies_without_a_cloud_target(
    tmp_path: Path,
) -> None:
    original = read_json(plan_path(tmp_path))
    row = {k: v for k, v in original["requests"][0].items() if k != "request_id"}
    model = "gemma4:e2b-it-qat"
    row["model"] = model
    row["request"]["model"] = model
    row["request"]["think"] = False
    frozen = write_plan(
        tmp_path / "gemma-plan",
        rows=[row],
        metadata={"evidence_kind": "TEST_FIXTURE_NOT_MODEL_BENCHMARK"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "127.0.0.1"
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "TEST_FIXTURE"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": model, "digest": "a" * 64}]})
        assert json.loads(request.content)["model"] == model
        return httpx.Response(
            200,
            json={
                "model": model,
                "done": True,
                "done_reason": "stop",
                "message": {"content": "[]"},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        outcome = execute_plan(frozen, tmp_path / "gemma-run", client=client)
    assert outcome["statuses"] == {"RESPONDED": 1}
    assert verify_run(tmp_path / "gemma-run")["recorded_target_calls"] == 1


def test_timeout_remains_failure_and_is_not_retried(tmp_path: Path) -> None:
    path = plan_path(tmp_path)
    calls: list[str] = []
    with local_client(calls, fail=True) as client:
        result = execute_plan(path, tmp_path / "run", client=client)
        execute_plan(path, tmp_path / "run", client=client)
    assert result["statuses"] == {"REQUEST_FAILED": 1}
    assert len(calls) == 1


def test_context_budget_blocks_before_target_call_and_retains_denominator(tmp_path: Path) -> None:
    path = plan_path(tmp_path, budget=1)
    calls: list[str] = []
    with local_client(calls) as client:
        result = execute_plan(path, tmp_path / "run", client=client)
    assert result["planned"] == 1
    assert result["statuses"] == {"CONTEXT_BLOCKED": 1}
    assert calls == []


def test_unknown_attempt_is_not_reissued(tmp_path: Path) -> None:
    path = plan_path(tmp_path)
    calls: list[str] = []
    with local_client(calls) as client:
        execute_plan(path, tmp_path / "run", client=client)
        next((tmp_path / "run" / "attempts").glob("*.result.json")).unlink()
        result = execute_plan(path, tmp_path / "run", client=client)
    assert len(calls) == 1
    assert result["complete"] is False
    assert result["statuses"] == {"ATTEMPT_OUTCOME_UNKNOWN": 1}


def test_result_tamper_is_rejected_offline(tmp_path: Path) -> None:
    path = plan_path(tmp_path)
    with local_client([]) as client:
        execute_plan(path, tmp_path / "run", client=client)
    result_file = next((tmp_path / "run" / "attempts").glob("*.result.json"))
    value = read_json(result_file)
    value["response"]["message"]["content"] = "invented result"
    result_file.write_bytes(encoded(value))
    with pytest.raises(ValueError, match="result_hash_mismatch"):
        verify_run(tmp_path / "run")


def test_rehashed_fake_success_without_response_is_rejected(tmp_path: Path) -> None:
    path = plan_path(tmp_path)
    with local_client([], fail=True) as client:
        execute_plan(path, tmp_path / "run", client=client)
    result_file = next((tmp_path / "run" / "attempts").glob("*.result.json"))
    value = read_json(result_file)
    value["status"] = "RESPONDED"
    value["result_sha256"] = digest({k: v for k, v in value.items() if k != "result_sha256"})
    result_file.write_bytes(encoded(value))
    with pytest.raises(ValueError, match="missing_success_response"):
        verify_run(tmp_path / "run")


def test_changed_dataset_plan_is_rejected_before_network(tmp_path: Path) -> None:
    path = plan_path(tmp_path)
    value = read_json(path)
    value["requests"][0]["case_id"] = "another-case"
    path.write_bytes(encoded(value))
    with pytest.raises(ValueError, match="plan_hash_mismatch"):
        execute_plan(path, tmp_path / "run")


def test_existing_output_is_never_overwritten(tmp_path: Path) -> None:
    path = plan_path(tmp_path)
    output = tmp_path / "run"
    output.mkdir()
    previous = output / "important.txt"
    previous.write_text("preserve")
    with local_client([]) as client, pytest.raises(ValueError, match="output_not_empty"):
        execute_plan(path, output, client=client)
    assert previous.read_text() == "preserve"


@pytest.mark.parametrize("called", [False, 0, "false"])
def test_rehashed_success_cannot_hide_actual_target_call(tmp_path: Path, called: object) -> None:
    path = plan_path(tmp_path)
    with local_client([]) as client:
        execute_plan(path, tmp_path / "run", client=client)
    result_file = next((tmp_path / "run" / "attempts").glob("*.result.json"))
    result = read_json(result_file)
    result["called"] = called
    result["result_sha256"] = digest({k: v for k, v in result.items() if k != "result_sha256"})
    result_file.write_bytes(encoded(result))
    with pytest.raises(ValueError, match="called_status_mismatch"):
        verify_run(tmp_path / "run")


@pytest.mark.parametrize(
    ("budget", "changes", "error"),
    [
        (6000, {"wall_seconds": True}, "invalid_wall_time"),
        (
            6000,
            {"status": "CONTEXT_BLOCKED", "called": False, "response": None},
            "context_status_mismatch",
        ),
        (1, {"status": "REQUEST_FAILED", "called": True}, "context_status_mismatch"),
    ],
    ids=["bool-wall-time", "invented-context-block", "called-over-budget"],
)
def test_rehashed_receipt_must_match_context_and_numeric_contract(
    tmp_path: Path,
    budget: int,
    changes: dict[str, object],
    error: str,
) -> None:
    path = plan_path(tmp_path, budget=budget)
    with local_client([]) as client:
        execute_plan(path, tmp_path / "run", client=client)
    result_file = next((tmp_path / "run" / "attempts").glob("*.result.json"))
    result = read_json(result_file)
    result.update(changes)
    result["result_sha256"] = digest({k: v for k, v in result.items() if k != "result_sha256"})
    result_file.write_bytes(encoded(result))
    with pytest.raises(ValueError, match=error):
        verify_run(tmp_path / "run")


def test_resume_rejects_broken_ledger_before_any_network_request(tmp_path: Path) -> None:
    path = plan_path(tmp_path)
    with local_client([]) as client:
        execute_plan(path, tmp_path / "run", client=client)
    result_file = next((tmp_path / "run" / "attempts").glob("*.result.json"))
    result = read_json(result_file)
    result["response"]["message"]["content"] = "tampered"
    result_file.write_bytes(encoded(result))
    network_requests: list[str] = []

    def must_not_contact(request: httpx.Request) -> httpx.Response:
        network_requests.append(request.url.path)
        raise AssertionError("network_before_existing_ledger_verification")

    with (
        httpx.Client(transport=httpx.MockTransport(must_not_contact)) as client,
        pytest.raises(ValueError, match="result_hash_mismatch"),
    ):
        execute_plan(path, tmp_path / "run", client=client)
    assert network_requests == []


@pytest.mark.parametrize("field", ["remote_model", "remote_host"])
def test_approved_tag_cannot_route_to_remote_inventory_model(tmp_path: Path, field: str) -> None:
    path = plan_path(tmp_path)
    calls: list[str] = []
    with (
        local_client(calls, remote_field=field) as client,
        pytest.raises(ValueError, match="remote_model_not_allowed"),
    ):
        execute_plan(path, tmp_path / "run", client=client)
    assert calls == []


def test_core_plan_rejects_unapproved_model_even_with_local_looking_tag(tmp_path: Path) -> None:
    path = plan_path(tmp_path)
    row = read_json(path)["requests"][0]
    del row["request_id"]
    row["model"] = row["request"]["model"] = "unapproved:local"
    with pytest.raises(ValueError, match="unapproved_local_model"):
        write_plan(tmp_path / "unapproved", rows=[row], metadata={"fixture": True})


def test_http_failure_keeps_status_without_headers_or_error_body(tmp_path: Path) -> None:
    path = plan_path(tmp_path)
    calls: list[str] = []
    with local_client(calls, http_failure=503) as client:
        outcome = execute_plan(path, tmp_path / "run", client=client)
    result_file = next((tmp_path / "run" / "attempts").glob("*.result.json"))
    result = read_json(result_file)
    assert outcome["statuses"] == {"REQUEST_FAILED": 1}
    assert result.get("http_status_code") == 503
    assert result["error_type"] == "HTTPStatusError"
    assert result["called"] is True
    assert result["response"] is None
    assert "DO-NOT-RECORD" not in result_file.read_text(encoding="utf-8")


@pytest.mark.parametrize("http_status", [503, True, "503"])
def test_rehashed_success_cannot_claim_http_failure_code(
    tmp_path: Path,
    http_status: object,
) -> None:
    path = plan_path(tmp_path)
    with local_client([]) as client:
        execute_plan(path, tmp_path / "run", client=client)
    result_file = next((tmp_path / "run" / "attempts").glob("*.result.json"))
    result = read_json(result_file)
    result["http_status_code"] = http_status
    result["result_sha256"] = digest({k: v for k, v in result.items() if k != "result_sha256"})
    result_file.write_bytes(encoded(result))
    with pytest.raises(ValueError, match="http_status_contract_mismatch"):
        verify_run(tmp_path / "run")


def test_context_budget_cannot_be_boolean(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="context_budget_required"):
        plan_path(tmp_path, budget=True)
