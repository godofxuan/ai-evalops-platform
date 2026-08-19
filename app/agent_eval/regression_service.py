"""Tenant-scoped Agent Run comparison over persisted trajectory evaluator evidence."""

from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.agent_eval.failure_taxonomy import classify_agent_failure
from app.agent_eval.regression import (
    AgentComparisonCase,
    AgentRegressionGate,
    compare_agent_runs,
)
from app.agent_eval.schemas import AgentRegressionRequest, AgentRegressionResponse
from app.auth.principals import Principal
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    AgentEvaluationResultRecord,
    AgentExecutionArtifact,
    EvaluationRun,
)
from app.runs.service import RunNotFoundError


class SQLAlchemyAgentRegressionService:
    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def compare(
        self,
        *,
        principal: Principal,
        request: AgentRegressionRequest,
    ) -> AgentRegressionResponse:
        async with self._session_factory() as session:
            owned_ids = set(
                (
                    await session.execute(
                        select(EvaluationRun.id).where(
                            EvaluationRun.tenant_id == principal.tenant_id,
                            EvaluationRun.id.in_((request.left_run_id, request.right_run_id)),
                        )
                    )
                ).scalars()
            )
            if owned_ids != {request.left_run_id, request.right_run_id}:
                raise RunNotFoundError
            left = await _load_run_cases(
                session,
                tenant_id=principal.tenant_id,
                run_id=request.left_run_id,
            )
            right = await _load_run_cases(
                session,
                tenant_id=principal.tenant_id,
                run_id=request.right_run_id,
            )

        report = compare_agent_runs(left, right)
        decision = AgentRegressionGate(**request.gate.model_dump()).assess(report)
        return AgentRegressionResponse(
            intersection_count=report.intersection_count,
            left_only_count=report.left_only_count,
            right_only_count=report.right_only_count,
            task_success_rate=report.task_success_rate,
            latency_p95_ms=report.latency_p95_ms,
            permission_violation_count=report.permission_violation_count,
            terminal_distribution=report.terminal_distribution,
            failure_category_distribution=report.failure_category_distribution,
            gate_passed=decision.passed,
            gate_violations=list(decision.violations),
        )


async def _load_run_cases(
    session: Any,
    *,
    tenant_id: UUID,
    run_id: UUID,
) -> dict[str, AgentComparisonCase]:
    rows = (
        await session.execute(
            select(AgentExecutionArtifact, AgentEvaluationResultRecord)
            .outerjoin(
                AgentEvaluationResultRecord,
                AgentEvaluationResultRecord.artifact_id == AgentExecutionArtifact.id,
            )
            .where(
                AgentExecutionArtifact.tenant_id == tenant_id,
                AgentExecutionArtifact.run_id == run_id,
            )
            .order_by(
                AgentExecutionArtifact.case_id,
                AgentExecutionArtifact.created_at.desc(),
                AgentExecutionArtifact.id.desc(),
                AgentEvaluationResultRecord.evaluator_kind,
                AgentEvaluationResultRecord.created_at.desc(),
            )
        )
    ).all()
    by_case: dict[str, list[tuple[AgentExecutionArtifact, AgentEvaluationResultRecord | None]]] = (
        defaultdict(list)
    )
    for artifact, result in rows:
        by_case[artifact.case_id].append((artifact, result))

    cases: dict[str, AgentComparisonCase] = {}
    for case_id, evidence_rows in by_case.items():
        selected_artifact = evidence_rows[0][0]
        metrics: dict[str, Any] = {}
        selected_kinds: set[str] = set()
        for artifact, result in evidence_rows:
            if artifact.id != selected_artifact.id or result is None:
                continue
            if result.evaluator_kind in selected_kinds:
                continue
            selected_kinds.add(result.evaluator_kind)
            _merge_metrics(metrics, result.metrics_json)
        terminal_state = selected_artifact.terminal_state or "unknown"
        metrics.setdefault("terminal_state", terminal_state)
        cases[case_id] = AgentComparisonCase(
            metrics=metrics,
            terminal_state=terminal_state,
            failure_category=classify_agent_failure(metrics),
        )
    return cases


def _merge_metrics(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for name, value in incoming.items():
        previous = target.get(name)
        if name in target and previous != value:
            raise RuntimeError(f"conflicting Agent evaluator metric: {name}")
        target[name] = value
