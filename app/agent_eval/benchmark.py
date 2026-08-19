"""Deterministic benchmark replay for validating framework-neutral Agent adapters."""

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.agent_eval.evaluators import build_agent_evaluator, registered_agent_evaluators
from app.agent_eval.failure_taxonomy import classify_agent_failure
from app.agent_eval.regression import AgentComparisonCase, compare_agent_runs
from app.agent_eval.schema import AgentRunArtifact, artifact_content_sha256

BenchmarkFamily = Literal[
    "direct_lookup",
    "multi_step_retrieval",
    "denied_access",
    "missing_evidence",
    "conflicting_evidence",
    "tool_failure",
    "budget_limit",
    "injection_adversarial",
]


class BenchmarkEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["call", "result", "claim", "citation"]
    tool: str | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class BenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    case_id: str
    family: BenchmarkFamily
    input: dict[str, JsonValue]
    output: dict[str, JsonValue]
    evidence: dict[str, JsonValue]
    usage: dict[str, JsonValue]
    terminal: dict[str, JsonValue]
    events: list[BenchmarkEvent]


class BenchmarkDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["agent-eval-benchmark/v1"]
    cases: list[BenchmarkCase] = Field(min_length=1)


def load_benchmark_cases(path: Path) -> tuple[BenchmarkCase, ...]:
    document = BenchmarkDocument.model_validate_json(path.read_bytes())
    case_ids = [case.case_id for case in document.cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("benchmark case IDs must be unique")
    return tuple(document.cases)


def run_adapter_comparison(path: Path) -> dict[str, Any]:
    source = path.read_bytes()
    cases = load_benchmark_cases(path)
    custom = {case.case_id: _adapt_custom(case) for case in cases}
    langgraph = {case.case_id: _adapt_langgraph(case) for case in cases}
    custom_results = _evaluate(custom)
    langgraph_results = _evaluate(langgraph)
    report = compare_agent_runs(custom_results, langgraph_results)
    return {
        "schema_version": "agent-adapter-comparison/v1",
        "claim_scope": "deterministic adapter-contract replay; not runtime performance",
        "benchmark_sha256": hashlib.sha256(source).hexdigest(),
        "benchmark_case_count": len(cases),
        "adapters": ["custom-controller", "langgraph-adapter"],
        "artifact_sha256": {
            "custom-controller": {
                case_id: artifact_content_sha256(artifact)
                for case_id, artifact in custom.items()
            },
            "langgraph-adapter": {
                case_id: artifact_content_sha256(artifact)
                for case_id, artifact in langgraph.items()
            },
        },
        "comparison": {
            "intersection_count": report.intersection_count,
            "left_only_count": report.left_only_count,
            "right_only_count": report.right_only_count,
            "task_success_rate": report.task_success_rate,
            "latency_p95_ms": report.latency_p95_ms,
            "permission_violation_count": report.permission_violation_count,
            "terminal_distribution": report.terminal_distribution,
            "failure_category_distribution": report.failure_category_distribution,
        },
        "case_metrics": {
            "custom-controller": {
                case_id: item.metrics for case_id, item in custom_results.items()
            },
            "langgraph-adapter": {
                case_id: item.metrics for case_id, item in langgraph_results.items()
            },
        },
    }


def canonical_benchmark_evidence_bytes(evidence: dict[str, Any]) -> bytes:
    return json.dumps(
        evidence,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _adapt_custom(case: BenchmarkCase) -> AgentRunArtifact:
    event_names = {
        "call": "tool_call",
        "result": "tool_result",
        "claim": "claim",
        "citation": "citation",
    }
    return _artifact(
        case,
        framework="custom-controller",
        trajectory=[
            {
                "event_id": f"custom-{index}",
                "event_type": event_names[event.kind],
                "tool_name": event.tool,
                "payload": event.payload,
            }
            for index, event in enumerate(case.events, start=1)
        ],
    )


def _adapt_langgraph(case: BenchmarkCase) -> AgentRunArtifact:
    graph_events = [
        {
            "event": {
                "call": "on_tool_start",
                "result": "on_tool_end",
                "claim": "on_chain_claim",
                "citation": "on_chain_citation",
            }[event.kind],
            "name": event.tool,
            "data": event.payload,
        }
        for event in case.events
    ]
    semantic_names = {
        "on_tool_start": "tool_call",
        "on_tool_end": "tool_result",
        "on_chain_claim": "claim",
        "on_chain_citation": "citation",
    }
    return _artifact(
        case,
        framework="langgraph-adapter",
        trajectory=[
            {
                "event_id": f"langgraph-{index}",
                "event_type": semantic_names[str(event["event"])],
                "tool_name": event["name"],
                "payload": event["data"],
            }
            for index, event in enumerate(graph_events, start=1)
        ],
    )


def _artifact(
    case: BenchmarkCase,
    *,
    framework: str,
    trajectory: list[dict[str, Any]],
) -> AgentRunArtifact:
    return AgentRunArtifact.model_validate(
        {
            "schema_version": "agent-run-artifact/v1",
            "run_id": "benchmark-v1",
            "case_id": case.case_id,
            "session_id": f"{framework}-{case.case_id}",
            "framework": framework,
            "input": case.input,
            "output": case.output,
            "trajectory": trajectory,
            "evidence": case.evidence,
            "usage": case.usage,
            "terminal": case.terminal,
            "metadata": {"benchmark_family": case.family},
        }
    )


def _evaluate(artifacts: dict[str, AgentRunArtifact]) -> dict[str, AgentComparisonCase]:
    cases: dict[str, AgentComparisonCase] = {}
    for case_id, artifact in artifacts.items():
        metrics: dict[str, Any] = {}
        for descriptor in registered_agent_evaluators():
            result = build_agent_evaluator(descriptor.kind, {}).evaluate(artifact)
            _merge_metrics(metrics, result.metrics)
        cases[case_id] = AgentComparisonCase(
            metrics=metrics,
            terminal_state=artifact.terminal.state,
            failure_category=classify_agent_failure(metrics),
        )
    return cases


def _merge_metrics(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for name, value in incoming.items():
        if name in target and target[name] != value:
            raise RuntimeError(f"conflicting benchmark evaluator metric: {name}")
        target[name] = value
