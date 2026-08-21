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
