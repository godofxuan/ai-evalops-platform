"""Official MCP SDK adapter with per-call authorization and safe auditing."""

from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol
from uuid import uuid4

from mcp.server import MCPServer

from app.agent_eval.control_plane import McpEvalControlPlane
from app.auth.principals import Principal


class McpCallAuthorizer(Protocol):
    def authorize(self, *, tool_name: str) -> AbstractAsyncContextManager[Principal]:
        """Revalidate and hold the credential authorization for one call."""


class McpCallAuditor(Protocol):
    async def record(
        self,
        *,
        principal: Principal,
        tool_name: str,
        status: str,
        trace_id: str,
    ) -> None:
        """Record only bounded credential and outcome metadata."""


def build_mcp_server(
    *,
    control_plane: McpEvalControlPlane,
    authorizer: McpCallAuthorizer,
    auditor: McpCallAuditor,
    credential_identity: Principal,
) -> MCPServer[Any]:
    server: MCPServer[Any] = MCPServer(
        "ai-evalops",
        title="AI EvalOps Agent Evaluation Control Plane",
        description="Tenant-scoped evaluation, trajectory and regression operations.",
        version="0.1.0",
    )

    async def invoke(name: str, arguments: dict[str, object]) -> dict[str, object]:
        trace_id = uuid4().hex
        principal = credential_identity
        try:
            async with authorizer.authorize(tool_name=name) as current_principal:
                principal = current_principal
                result = await control_plane.call_tool(
                    principal=current_principal,
                    name=name,
                    arguments=arguments,
                )
            await auditor.record(
                principal=principal,
                tool_name=name,
                status="succeeded",
                trace_id=trace_id,
            )
            return result
        except Exception:
            await auditor.record(
                principal=principal,
                tool_name=name,
                status="failed",
                trace_id=trace_id,
            )
            raise

    @server.tool(name="submit_evaluation")
    async def submit_evaluation(
        idempotency_key: str,
        request: dict[str, object],
    ) -> dict[str, object]:
        return await invoke(
            "submit_evaluation", {"idempotency_key": idempotency_key, "request": request}
        )

    @server.tool(name="get_run_status")
    async def get_run_status(run_id: str) -> dict[str, object]:
        return await invoke("get_run_status", {"run_id": run_id})

    @server.tool(name="list_failed_cases")
    async def list_failed_cases(run_id: str, limit: int = 50) -> dict[str, object]:
        return await invoke("list_failed_cases", {"run_id": run_id, "limit": limit})

    @server.tool(name="get_case_result")
    async def get_case_result(run_id: str, case_id: str) -> dict[str, object]:
        return await invoke("get_case_result", {"run_id": run_id, "case_id": case_id})

    @server.tool(name="get_case_trajectory")
    async def get_case_trajectory(run_id: str, artifact_id: str) -> dict[str, object]:
        return await invoke("get_case_trajectory", {"run_id": run_id, "artifact_id": artifact_id})

    @server.tool(name="compare_runs")
    async def compare_runs(left_run_id: str, right_run_id: str) -> dict[str, object]:
        return await invoke(
            "compare_runs", {"left_run_id": left_run_id, "right_run_id": right_run_id}
        )

    @server.tool(name="get_regression_summary")
    async def get_regression_summary(
        left_run_id: str,
        right_run_id: str,
        gate: dict[str, object],
    ) -> dict[str, object]:
        return await invoke(
            "get_regression_summary",
            {"left_run_id": left_run_id, "right_run_id": right_run_id, "gate": gate},
        )

    return server
