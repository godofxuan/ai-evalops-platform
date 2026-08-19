"""Tenant-scoped immutable Agent Run regression comparisons."""

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.agent_eval.failure_taxonomy import classify_agent_failure
from app.agent_eval.regression import AgentComparisonCase, AgentRegressionGate, compare_agent_runs
from app.agent_eval.schemas import (
    AgentCommonCaseMetricsRead,
    AgentComparisonEvidenceRead,
    AgentRegressionRequest,
    AgentRegressionResponse,
    AgentRunDiagnosticsRead,
)
from app.auth.principals import Principal
from app.persistence.database import AsyncSessionFactory
from app.persistence.orm_models import (
    AgentEvaluationResultRecord,
    AgentExecutionArtifact,
    AgentRegressionComparison,
    AgentRegressionEvidence,
    EvaluationRun,
)
from app.runs.service import RunNotFoundError


@dataclass(frozen=True, slots=True)
class _ResolvedCase:
    comparison_case: AgentComparisonCase
    artifact: AgentExecutionArtifact
    results: dict[str, AgentEvaluationResultRecord]


class SQLAlchemyAgentRegressionService:
    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def compare(
        self,
        *,
        principal: Principal,
        request: AgentRegressionRequest,
    ) -> AgentRegressionResponse:
        request_sha256 = _request_sha256(request)
        async with self._session_factory.begin() as session:
            existing = await session.scalar(
                select(AgentRegressionComparison).where(
                    AgentRegressionComparison.tenant_id == principal.tenant_id,
                    AgentRegressionComparison.request_sha256 == request_sha256,
                )
            )
            if existing is not None:
                evidence = await _load_manifest(session, existing)
                return _response(existing, evidence)

            run_rows = (
                (
                    await session.execute(
                        select(EvaluationRun).where(
                            EvaluationRun.tenant_id == principal.tenant_id,
                            EvaluationRun.id.in_((request.left_run_id, request.right_run_id)),
                        )
                    )
                )
                .scalars()
                .all()
            )
            runs = {run.id: run for run in run_rows}
            if set(runs) != {request.left_run_id, request.right_run_id}:
                raise RunNotFoundError
            left = await _resolve_run_evidence(
                session, tenant_id=principal.tenant_id, run_id=request.left_run_id
            )
            right = await _resolve_run_evidence(
                session, tenant_id=principal.tenant_id, run_id=request.right_run_id
            )
            report = compare_agent_runs(
                {case_id: item.comparison_case for case_id, item in left.items()},
                {case_id: item.comparison_case for case_id, item in right.items()},
                case_set_policy=request.gate.case_set_policy,
            )
            decision = AgentRegressionGate(**request.gate.model_dump()).assess(report)
            comparison_id = uuid4()
            created_at = datetime.now(UTC)
            values = {
                "id": comparison_id,
                "tenant_id": principal.tenant_id,
                "left_run_id": request.left_run_id,
                "right_run_id": request.right_run_id,
                "left_dataset_version_id": runs[request.left_run_id].dataset_version_id,
                "right_dataset_version_id": runs[request.right_run_id].dataset_version_id,
                "request_sha256": request_sha256,
                "case_set_policy": request.gate.case_set_policy,
                "gate_config_json": request.gate.model_dump(mode="json"),
                "report_json": asdict(report),
                "decision_json": asdict(decision),
                "created_at": created_at,
            }
            inserted_id = await session.scalar(
                insert(AgentRegressionComparison)
                .values(**values)
                .on_conflict_do_nothing(constraint="uq_agent_regression_comparison_request")
                .returning(AgentRegressionComparison.id)
            )
            if inserted_id is None:
                existing = await session.scalar(
                    select(AgentRegressionComparison).where(
                        AgentRegressionComparison.tenant_id == principal.tenant_id,
                        AgentRegressionComparison.request_sha256 == request_sha256,
                    )
                )
                if existing is None:
                    raise RuntimeError("comparison idempotency conflict did not resolve")
                evidence = await _load_manifest(session, existing)
                return _response(existing, evidence)

            manifest = _build_manifest(
                comparison_id=comparison_id,
                tenant_id=principal.tenant_id,
                left_run_id=request.left_run_id,
                right_run_id=request.right_run_id,
                left_dataset_version_id=runs[request.left_run_id].dataset_version_id,
                right_dataset_version_id=runs[request.right_run_id].dataset_version_id,
                common_case_ids=report.common_case_ids,
                left=left,
                right=right,
            )
            session.add_all(manifest)
            comparison = AgentRegressionComparison(**values)
            response_manifest = [_manifest_read(item, comparison) for item in manifest]
            return _response(comparison, response_manifest)


async def _resolve_run_evidence(
    session: Any,
    *,
    tenant_id: UUID,
    run_id: UUID,
) -> dict[str, _ResolvedCase]:
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
                AgentExecutionArtifact.case_id.asc(),
                AgentExecutionArtifact.created_at.desc(),
                AgentExecutionArtifact.id.desc(),
                AgentEvaluationResultRecord.evaluator_kind.asc(),
                AgentEvaluationResultRecord.created_at.desc(),
                AgentEvaluationResultRecord.id.desc(),
            )
        )
    ).all()
    by_case: dict[str, list[tuple[AgentExecutionArtifact, AgentEvaluationResultRecord | None]]] = (
        defaultdict(list)
    )
    for artifact, result in rows:
        by_case[artifact.case_id].append((artifact, result))

    resolved: dict[str, _ResolvedCase] = {}
    for case_id, evidence_rows in by_case.items():
        selected_artifact = evidence_rows[0][0]
        metrics: dict[str, Any] = {}
        metric_trust: dict[str, str] = {}
        selected_results: dict[str, AgentEvaluationResultRecord] = {}
        for artifact, result in evidence_rows:
            if artifact.id != selected_artifact.id or result is None:
                continue
            if result.evaluator_kind in selected_results:
                continue
            selected_results[result.evaluator_kind] = result
            _merge_metrics(metrics, result.metrics_json)
            _merge_metric_trust(metric_trust, result.metric_provenance_json)
        terminal_state = selected_artifact.terminal_state or "unknown"
        metrics.setdefault("terminal_state", terminal_state)
        resolved[case_id] = _ResolvedCase(
            comparison_case=AgentComparisonCase(
                metrics=metrics,
                terminal_state=terminal_state,
                failure_category=classify_agent_failure(metrics),
                metric_trust=metric_trust,
            ),
            artifact=selected_artifact,
            results=selected_results,
        )
    return resolved


def _build_manifest(
    *,
    comparison_id: UUID,
    tenant_id: UUID,
    left_run_id: UUID,
    right_run_id: UUID,
    left_dataset_version_id: UUID | None,
    right_dataset_version_id: UUID | None,
    common_case_ids: tuple[str, ...],
    left: dict[str, _ResolvedCase],
    right: dict[str, _ResolvedCase],
) -> list[AgentRegressionEvidence]:
    del left_dataset_version_id, right_dataset_version_id
    manifest: list[AgentRegressionEvidence] = []
    for case_id in common_case_ids:
        left_case = left[case_id]
        right_case = right[case_id]
        evaluator_kinds = sorted(set(left_case.results) | set(right_case.results))
        if not evaluator_kinds:
            evaluator_kinds = ["artifact_identity"]
        for kind in evaluator_kinds:
            left_result = left_case.results.get(kind)
            right_result = right_case.results.get(kind)
            manifest.append(
                AgentRegressionEvidence(
                    comparison_id=comparison_id,
                    tenant_id=tenant_id,
                    left_run_id=left_run_id,
                    right_run_id=right_run_id,
                    case_id=case_id,
                    left_artifact_id=left_case.artifact.id,
                    right_artifact_id=right_case.artifact.id,
                    evaluator_kind=kind,
                    left_evaluator_result_id=None if left_result is None else left_result.id,
                    right_evaluator_result_id=None if right_result is None else right_result.id,
                    left_implementation_version=(
                        None if left_result is None else left_result.evaluator_version
                    ),
                    right_implementation_version=(
                        None if right_result is None else right_result.evaluator_version
                    ),
                    left_config_sha256=(None if left_result is None else left_result.config_sha256),
                    right_config_sha256=(
                        None if right_result is None else right_result.config_sha256
                    ),
                )
            )
    return manifest


async def _load_manifest(
    session: Any,
    comparison: AgentRegressionComparison,
) -> list[AgentComparisonEvidenceRead]:
    rows = (
        await session.execute(
            select(AgentRegressionEvidence)
            .where(
                AgentRegressionEvidence.tenant_id == comparison.tenant_id,
                AgentRegressionEvidence.comparison_id == comparison.id,
            )
            .order_by(
                AgentRegressionEvidence.case_id.asc(),
                AgentRegressionEvidence.evaluator_kind.asc(),
                AgentRegressionEvidence.id.asc(),
            )
        )
    ).scalars()
    return [_manifest_read(item, comparison) for item in rows]


def _manifest_read(
    item: AgentRegressionEvidence,
    comparison: AgentRegressionComparison,
) -> AgentComparisonEvidenceRead:
    return AgentComparisonEvidenceRead(
        case_id=item.case_id,
        left_artifact_id=item.left_artifact_id,
        right_artifact_id=item.right_artifact_id,
        evaluator_kind=item.evaluator_kind,
        left_evaluator_result_id=item.left_evaluator_result_id,
        right_evaluator_result_id=item.right_evaluator_result_id,
        left_implementation_version=item.left_implementation_version,
        right_implementation_version=item.right_implementation_version,
        left_config_sha256=item.left_config_sha256,
        right_config_sha256=item.right_config_sha256,
        left_dataset_version_id=comparison.left_dataset_version_id,
        right_dataset_version_id=comparison.right_dataset_version_id,
    )


def _response(
    comparison: AgentRegressionComparison,
    evidence: list[AgentComparisonEvidenceRead],
) -> AgentRegressionResponse:
    report = comparison.report_json
    decision = comparison.decision_json
    return AgentRegressionResponse(
        comparison_id=comparison.id,
        left_run_id=comparison.left_run_id,
        right_run_id=comparison.right_run_id,
        case_set_policy=comparison.case_set_policy,
        common_case_ids=list(report["common_case_ids"]),
        common_case_ids_sha256=report["common_case_ids_sha256"],
        intersection_count=report["intersection_count"],
        left_only_case_ids=list(report["left_only_case_ids"]),
        right_only_case_ids=list(report["right_only_case_ids"]),
        left_only_count=report["left_only_count"],
        right_only_count=report["right_only_count"],
        common_case_metrics=AgentCommonCaseMetricsRead(
            task_success_rate=report["task_success_rate"],
            latency_p95_ms=report["latency_p95_ms"],
            unauthorized_result_leak_count=report["permission_violation_count"],
            tool_error_rate=report["tool_error_rate"],
            terminal_distribution=report["terminal_distribution"],
            failure_category_distribution=report["failure_category_distribution"],
            metric_evidence=report["metric_evidence"],
            metric_trust=report["metric_trust"],
        ),
        left_full_run_diagnostics=AgentRunDiagnosticsRead.model_validate(
            report["left_full_run_diagnostics"]
        ),
        right_full_run_diagnostics=AgentRunDiagnosticsRead.model_validate(
            report["right_full_run_diagnostics"]
        ),
        evidence_manifest=evidence,
        gate_executed=decision["gate_executed"],
        evidence_sufficient=decision["evidence_sufficient"],
        gate_status=decision["status"],
        gate_passed=decision["passed"],
        gate_violations=list(decision["violations"]),
        warnings=list(decision["warnings"]),
        created_at=comparison.created_at,
    )


def _request_sha256(request: AgentRegressionRequest) -> str:
    payload = json.dumps(
        request.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _merge_metrics(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for name, value in incoming.items():
        previous = target.get(name)
        if name in target and previous != value:
            raise RuntimeError(f"conflicting Agent evaluator metric: {name}")
        target[name] = value


def _merge_metric_trust(target: dict[str, str], incoming: dict[str, str]) -> None:
    for name, value in incoming.items():
        previous = target.get(name)
        if name in target and previous != value:
            raise RuntimeError(f"conflicting Agent evaluator metric provenance: {name}")
        target[name] = value
