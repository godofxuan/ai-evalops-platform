"""MCP tool surface that delegates to authenticated EvalOps service-layer operations."""

from collections.abc import Mapping
from typing import Protocol

from app.auth.principals import Principal


class McpEvalServices(Protocol):
    async def invoke(
        self,
        *,
        tool_name: str,
        principal: Principal,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        """Call an existing API/service operation after host authentication."""


class McpToolNotFoundError(ValueError):
    pass


class McpEvalControlPlane:
    """Transport-independent MCP tool dispatcher.

    An MCP transport adapter must authenticate the caller first and supply the derived Principal.
    This class does not own credentials or access PostgreSQL directly. It has no second auth path.
    """

    _TOOLS = (
        "submit_evaluation",
        "get_run_status",
        "list_failed_cases",
        "get_case_result",
        "get_case_trajectory",
        "compare_runs",
        "get_regression_summary",
    )

    def __init__(self, *, services: McpEvalServices) -> None:
        self._services = services

    def tool_definitions(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "name": name,
                "description": _description(name),
                "inputSchema": {"type": "object", "additionalProperties": True},
            }
            for name in self._TOOLS
        )

    async def call_tool(
        self,
        *,
        principal: Principal,
        name: str,
        arguments: Mapping[str, object],
    ) -> dict[str, object]:
        if name not in self._TOOLS:
            raise McpToolNotFoundError(name)
        return await self._services.invoke(
            tool_name=name,
            principal=principal,
            arguments=dict(arguments),
        )


def _description(name: str) -> str:
    return {
        "submit_evaluation": "Submit an idempotent EvalOps Run through the existing Run service.",
        "get_run_status": "Read a tenant-scoped EvalOps Run snapshot.",
        "list_failed_cases": "List failed cases through the existing Result service.",
        "get_case_result": "Read one tenant-scoped case result.",
        "get_case_trajectory": "Read an authorized immutable Agent execution artifact.",
        "compare_runs": "Compare two tenant-scoped Runs with their existing comparison contract.",
        "get_regression_summary": "Read an Agent regression report and configured gate decision.",
    }[name]
