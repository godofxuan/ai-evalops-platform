"""Concrete MCP-to-domain service mapping with no database or authentication bypass."""

from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from app.agent_eval.schemas import (
    AgentArtifactDetailRead,
    AgentRegressionRequest,
    AgentRegressionResponse,
)
from app.auth.principals import Principal
from app.domain.enums import JobStatus
from app.results.schemas import CasePage, CaseQuery, CaseRead, RunComparisonRead
from app.runs.schemas import RunCreate, RunRead


class McpRunService(Protocol):
    async def create_run(
        self, *, principal: Principal, idempotency_key: str, request: RunCreate
    ) -> RunRead: ...

    async def get_run(self, *, principal: Principal, run_id: UUID) -> RunRead: ...


class McpResultService(Protocol):
    async def list_cases(
        self, *, principal: Principal, run_id: UUID, query: CaseQuery
    ) -> CasePage: ...

    async def get_case(self, *, principal: Principal, run_id: UUID, case_id: str) -> CaseRead: ...

    async def compare_runs(
        self,
        *,
        principal: Principal,
        left_run_id: UUID,
        right_run_id: UUID,
    ) -> RunComparisonRead: ...


class McpAgentArtifactService(Protocol):
    async def get(
        self, *, principal: Principal, run_id: UUID, artifact_id: UUID
    ) -> AgentArtifactDetailRead: ...


class McpAgentRegressionService(Protocol):
    async def compare(
        self, *, principal: Principal, request: AgentRegressionRequest
    ) -> AgentRegressionResponse: ...


class EvalOpsMcpServiceAdapter:
    """Translate MCP JSON arguments into existing typed service calls."""

    def __init__(
        self,
        *,
        run_service: McpRunService,
        result_service: McpResultService,
        agent_artifact_service: McpAgentArtifactService,
        agent_regression_service: McpAgentRegressionService,
    ) -> None:
        self._run_service = run_service
        self._result_service = result_service
        self._agent_artifact_service = agent_artifact_service
        self._agent_regression_service = agent_regression_service

    async def invoke(
        self,
        *,
        tool_name: str,
        principal: Principal,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        if tool_name == "submit_evaluation":
            created = await self._run_service.create_run(
                principal=principal,
                idempotency_key=_required_str(arguments, "idempotency_key"),
                request=RunCreate.model_validate(_required_mapping(arguments, "request")),
            )
            return created.model_dump(mode="json")
        if tool_name == "get_run_status":
            run = await self._run_service.get_run(
                principal=principal,
                run_id=_required_uuid(arguments, "run_id"),
            )
            return run.model_dump(mode="json")
        if tool_name == "list_failed_cases":
            limit = arguments.get("limit", 50)
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise ValueError("limit must be an integer")
            page = await self._result_service.list_cases(
                principal=principal,
                run_id=_required_uuid(arguments, "run_id"),
                query=CaseQuery(limit=limit, status=JobStatus.FAILED),
            )
            return page.model_dump(mode="json")
        if tool_name == "get_case_result":
            item = await self._result_service.get_case(
                principal=principal,
                run_id=_required_uuid(arguments, "run_id"),
                case_id=_required_str(arguments, "case_id"),
            )
            return item.model_dump(mode="json")
        if tool_name == "get_case_trajectory":
            artifact = await self._agent_artifact_service.get(
                principal=principal,
                run_id=_required_uuid(arguments, "run_id"),
                artifact_id=_required_uuid(arguments, "artifact_id"),
            )
            return artifact.model_dump(mode="json")
        if tool_name == "compare_runs":
            comparison = await self._result_service.compare_runs(
                principal=principal,
                left_run_id=_required_uuid(arguments, "left_run_id"),
                right_run_id=_required_uuid(arguments, "right_run_id"),
            )
            return comparison.model_dump(mode="json")
        if tool_name == "get_regression_summary":
            response = await self._agent_regression_service.compare(
                principal=principal,
                request=AgentRegressionRequest.model_validate(arguments),
            )
            return response.model_dump(mode="json")
        raise ValueError(f"unsupported MCP tool: {tool_name}")


def _required_str(arguments: Mapping[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _required_uuid(arguments: Mapping[str, object], name: str) -> UUID:
    return UUID(_required_str(arguments, name))


def _required_mapping(arguments: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = arguments.get(name)
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value
