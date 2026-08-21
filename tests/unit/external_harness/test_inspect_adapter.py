import pytest
from inspect_ai.log import EvalLog

from app.agent_eval.schema import artifact_content_sha256
from app.external_harness.inspect_adapter import convert_inspect_log_to_artifact


def test_inspect_log_converts_to_stable_agent_artifact() -> None:
    inspect_log = {
        "version": 2,
        "status": "success",
        "eval": {
            "eval_id": "eval-001",
            "task": "rag_policy_eval",
            "model": "mockllm/model",
            "created": "2026-08-21T00:00:00Z",
        },
        "samples": [
            {
                "id": "grounded-answer",
                "input": "What is the remote policy?",
                "output": {"completion": "Remote work requires manager approval."},
                "scores": {"grounded": {"value": 1, "explanation": "citation present"}},
                "events": [
                    {
                        "event": "tool",
                        "id": "tool-1",
                        "function": "search",
                        "arguments": {"query": "remote policy"},
                        "result": "policy-7",
                    }
                ],
            }
        ],
    }

    first = convert_inspect_log_to_artifact(inspect_log, sample_index=0)
    second = convert_inspect_log_to_artifact(inspect_log, sample_index=0)

    assert first.schema_version == "agent-run-artifact/v1"
    assert first.framework == "inspect-ai"
    assert first.case_id == "grounded-answer"
    assert first.terminal.state == "answer"
    assert first.metadata["inspect_eval_id"] == "eval-001"
    assert first.metadata["inspect_log_version"] == 2
    assert first.metadata["model"] == "mockllm/model"
    assert first.trajectory[0].event_type == "tool_call"
    assert artifact_content_sha256(first) == artifact_content_sha256(second)


def test_real_inspect_eval_log_model_interoperates_without_fixture_translation() -> None:
    log = EvalLog.model_validate(
        {
            "version": 2,
            "status": "success",
            "eval": {
                "eval_id": "real-model-001",
                "created": "2026-08-21T00:00:00Z",
                "task": "rag_policy_eval",
                "dataset": {"name": "external_harness_v1", "samples": 1},
                "model": "mockllm/model",
                "config": {},
            },
            "samples": [
                {
                    "id": "real-inspect-sample",
                    "epoch": 1,
                    "input": "What is the remote policy?",
                    "target": "A grounded answer or refusal",
                    "output": {
                        "model": "mockllm/model",
                        "completion": "Manager approval is required.",
                    },
                    "scores": {},
                    "events": [],
                }
            ],
        }
    )

    artifact = convert_inspect_log_to_artifact(log, sample_index=0)

    assert artifact.case_id == "real-inspect-sample"


def _inspect_log(
    events: list[dict[str, object]],
    *,
    status: str = "success",
) -> dict[str, object]:
    return {
        "version": 2,
        "status": status,
        "eval": {
            "eval_id": "strict-001",
            "task": "strict_task",
            "model": "mockllm/model",
        },
        "samples": [
            {
                "id": "strict-case",
                "input": "prompt",
                "output": {"completion": "done"} if status == "success" else None,
                "scores": {},
                "events": events,
            }
        ],
    }


def test_inspect_unknown_partial_duplicate_order_and_version_fail_closed() -> None:
    unknown = _inspect_log([{"event": "future_event", "uuid": "event-1"}])
    with pytest.raises(ValueError, match="unsupported Inspect event"):
        convert_inspect_log_to_artifact(unknown, sample_index=0)

    diagnostic = convert_inspect_log_to_artifact(unknown, sample_index=0, mode="diagnostic")
    assert diagnostic.metadata["formal_gate_eligible"] is False
    assert diagnostic.metadata["unmapped_event_count"] == 1
    assert diagnostic.metadata["dropped_event_count"] == 0

    started = _inspect_log([], status="started")
    with pytest.raises(ValueError, match="terminal success"):
        convert_inspect_log_to_artifact(started, sample_index=0)
    partial = convert_inspect_log_to_artifact(started, sample_index=0, mode="diagnostic")
    assert partial.terminal.state == "partial"
    assert partial.metadata["partial"] is True
    assert partial.metadata["formal_gate_eligible"] is False

    duplicate = _inspect_log(
        [
            {"event": "info", "uuid": "same"},
            {"event": "step", "uuid": "same"},
        ]
    )
    with pytest.raises(ValueError, match="duplicate"):
        convert_inspect_log_to_artifact(duplicate, sample_index=0)

    out_of_order = _inspect_log(
        [
            {
                "event": "info",
                "uuid": "event-1",
                "timestamp": "2026-08-21T00:00:02Z",
            },
            {
                "event": "step",
                "uuid": "event-2",
                "timestamp": "2026-08-21T00:00:01Z",
            },
        ]
    )
    with pytest.raises(ValueError, match="timestamp order"):
        convert_inspect_log_to_artifact(out_of_order, sample_index=0)

    wrong_version = _inspect_log([])
    wrong_version["version"] = 1
    with pytest.raises(ValueError, match="unsupported Inspect log version"):
        convert_inspect_log_to_artifact(wrong_version, sample_index=0)

    with pytest.raises(ValueError, match="must be an object"):
        convert_inspect_log_to_artifact('{"truncated":', sample_index=0)
