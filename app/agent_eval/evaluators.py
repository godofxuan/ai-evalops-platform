"""Deterministic evaluators over framework-neutral Agent trajectory artifacts."""

import json
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from app.agent_eval.schema import AgentRunArtifact, TrajectoryEvent


@dataclass(frozen=True, slots=True)
class AgentEvaluationResult:
    metrics: dict[str, Any]


class AgentTrajectoryEvaluator(Protocol):
    def evaluate(self, artifact: AgentRunArtifact) -> AgentEvaluationResult:
        """Evaluate one immutable Agent execution artifact without side effects."""


@dataclass(frozen=True, slots=True)
class AgentEvaluatorDescriptor:
    kind: str
    implementation_version: str
    llm_judge: bool


@dataclass(frozen=True, slots=True)
class _Registration:
    descriptor: AgentEvaluatorDescriptor
    factory: Callable[[Mapping[str, Any]], AgentTrajectoryEvaluator]


class TaskSuccessEvaluator:
    def evaluate(self, artifact: AgentRunArtifact) -> AgentEvaluationResult:
        explicit = artifact.output.get("task_success")
        success = explicit if isinstance(explicit, bool) else None
        return AgentEvaluationResult(
            metrics={
                "task_success": success,
                "task_success_requires_human_review": success is None,
                "terminal_state": artifact.terminal.state,
            }
        )


class ToolCallValidityEvaluator:
    def evaluate(self, artifact: AgentRunArtifact) -> AgentEvaluationResult:
        calls = _events(artifact, "tool_call")
        valid = sum(_bool_payload(item, "args_valid") is True for item in calls)
        denied = sum(_bool_payload(item, "authorized") is False for item in calls)
        errors = sum(
            _bool_payload(item, "success") is False for item in _events(artifact, "tool_result")
        )
        return AgentEvaluationResult(
            metrics={
                "tool_calls_total": len(calls),
                "tool_calls_valid": valid,
                "tool_calls_invalid": len(calls) - valid,
                "tool_calls_denied": denied,
                "tool_calls_error": errors,
            }
        )


class TrajectoryEfficiencyEvaluator:
    def evaluate(self, artifact: AgentRunArtifact) -> AgentEvaluationResult:
        calls = _events(artifact, "tool_call")
        call_identities = [(item.tool_name, _canonical_payload(item.payload)) for item in calls]
        counts = Counter(call_identities)
        depths = [_numeric_payload(item, "depth") for item in artifact.trajectory]
        numeric_depths = [value for value in depths if value is not None]
        return AgentEvaluationResult(
            metrics={
                "step_count": len(artifact.trajectory),
                "tool_call_count": len(calls),
                "repeated_tool_call_count": sum(
                    count - 1 for count in counts.values() if count > 1
                ),
                "max_depth": max(numeric_depths, default=None),
            }
        )


class GroundingCitationEvaluator:
    def evaluate(self, artifact: AgentRunArtifact) -> AgentEvaluationResult:
        citations = _events(artifact, "citation")
        claims = _events(artifact, "claim")
        invalid = sum(_bool_payload(item, "valid") is False for item in citations)
        unsupported = sum(_bool_payload(item, "supported") is False for item in claims)
        return AgentEvaluationResult(
            metrics={
                "citation_count": len(citations),
                "citation_presence": bool(citations),
                "citation_invalid_count": invalid,
                "unsupported_claim_count": unsupported,
            }
        )


class PermissionBoundaryEvaluator:
    def evaluate(self, artifact: AgentRunArtifact) -> AgentEvaluationResult:
        calls = _events(artifact, "tool_call")
        denied = sum(_bool_payload(item, "authorized") is False for item in calls)
        leaked = sum(
            _bool_payload(item, "unauthorized_result_leaked") is True
            for item in _events(artifact, "tool_result")
        )
        return AgentEvaluationResult(
            metrics={
                "permission_denied_attempt_count": denied,
                "unauthorized_result_leak_count": leaked,
                "permission_boundary_passed": leaked == 0,
            }
        )


class TerminalStateEvaluator:
    def evaluate(self, artifact: AgentRunArtifact) -> AgentEvaluationResult:
        return AgentEvaluationResult(metrics={"terminal_state": artifact.terminal.state})


class CostLatencyEvaluator:
    def evaluate(self, artifact: AgentRunArtifact) -> AgentEvaluationResult:
        usage = artifact.usage
        cost = usage.get("cost")
        return AgentEvaluationResult(
            metrics={
                "latency_ms": _numeric_value(usage.get("latency_ms")),
                "model_calls": _integer_value(usage.get("model_calls")),
                "input_tokens": _integer_value(usage.get("input_tokens")),
                "output_tokens": _integer_value(usage.get("output_tokens")),
                "tool_latency_ms": _numeric_value(usage.get("tool_latency_ms")),
                "cost": _numeric_value(cost),
                "cost_available": _numeric_value(cost) is not None,
            }
        )


def _registry() -> dict[str, _Registration]:
    return {
        "task_success": _registration("task_success", lambda _config: TaskSuccessEvaluator()),
        "tool_call_validity": _registration(
            "tool_call_validity", lambda _config: ToolCallValidityEvaluator()
        ),
        "trajectory_efficiency": _registration(
            "trajectory_efficiency", lambda _config: TrajectoryEfficiencyEvaluator()
        ),
        "grounding_citation": _registration(
            "grounding_citation", lambda _config: GroundingCitationEvaluator()
        ),
        "permission_boundary": _registration(
            "permission_boundary", lambda _config: PermissionBoundaryEvaluator()
        ),
        "terminal_state": _registration("terminal_state", lambda _config: TerminalStateEvaluator()),
        "cost_latency": _registration("cost_latency", lambda _config: CostLatencyEvaluator()),
    }


def _registration(
    kind: str,
    factory: Callable[[Mapping[str, Any]], AgentTrajectoryEvaluator],
) -> _Registration:
    return _Registration(
        descriptor=AgentEvaluatorDescriptor(
            kind=kind,
            implementation_version="builtin-v1",
            llm_judge=False,
        ),
        factory=factory,
    )


def registered_agent_evaluators() -> tuple[AgentEvaluatorDescriptor, ...]:
    return tuple(item.descriptor for item in _registry().values())


def build_agent_evaluator(kind: str, config: Mapping[str, Any]) -> AgentTrajectoryEvaluator:
    try:
        return _registry()[kind].factory(config)
    except KeyError:
        raise ValueError(f"unsupported Agent evaluator type: {kind}") from None


def _events(artifact: AgentRunArtifact, event_type: str) -> list[TrajectoryEvent]:
    return [item for item in artifact.trajectory if item.event_type == event_type]


def _bool_payload(event: TrajectoryEvent, key: str) -> bool | None:
    value = event.payload.get(key)
    return value if isinstance(value, bool) else None


def _numeric_payload(event: TrajectoryEvent, key: str) -> float | int | None:
    return _numeric_value(event.payload.get(key))


def _numeric_value(value: object) -> float | int | None:
    return value if isinstance(value, (float, int)) and not isinstance(value, bool) else None


def _integer_value(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _canonical_payload(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
