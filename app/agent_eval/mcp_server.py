"""Official MCP SDK adapter for the authenticated EvalOps control plane."""

from typing import Any

from mcp.server import MCPServer

from app.agent_eval.control_plane import McpEvalControlPlane
from app.auth.principals import Principal


def build_mcp_server(
    *,
    control_plane: McpEvalControlPlane,
    principal: Principal,
) -> MCPServer[Any]:
    """Build a stdio-capable server bound to one already-authenticated Principal."""

    server: MCPServer[Any] = MCPServer(
        "ai-evalops",
        title="AI EvalOps Agent Evaluation Control Plane",
        description="Tenant-scoped evaluation, trajectory and regression operations.",
        version="0.1.0",
    )

    @server.tool(name="submit_evaluation")
    async def submit_evaluation(
        idempotency_key: str,
        request: dict[str, object],
    ) -> dict[str, object]:
        """Submit an idempotent evaluation Run."""

        return await control_plane.call_tool(
            principal=principal,
            name="submit_evaluation",
            arguments={"idempotency_key": idempotency_key, "request": request},
        )

    @server.tool(name="get_run_status")
    async def get_run_status(run_id: str) -> dict[str, object]:
        """Read a tenant-scoped Run snapshot."""

        return await control_plane.call_tool(
            principal=principal,
            name="get_run_status",
            arguments={"run_id": run_id},
        )

    @server.tool(name="list_failed_cases")
    async def list_failed_cases(run_id: str, limit: int = 50) -> dict[str, object]:
        """List failed cases for a tenant-scoped Run."""

        return await control_plane.call_tool(
            principal=principal,
            name="list_failed_cases",
            arguments={"run_id": run_id, "limit": limit},
        )

    @server.tool(name="get_case_result")
    async def get_case_result(run_id: str, case_id: str) -> dict[str, object]:
        """Read one case result from a tenant-scoped Run."""

        return await control_plane.call_tool(
            principal=principal,
            name="get_case_result",
            arguments={"run_id": run_id, "case_id": case_id},
        )

    @server.tool(name="get_case_trajectory")
    async def get_case_trajectory(run_id: str, artifact_id: str) -> dict[str, object]:
        """Read one authorized immutable Agent trajectory."""

        return await control_plane.call_tool(
            principal=principal,
            name="get_case_trajectory",
            arguments={"run_id": run_id, "artifact_id": artifact_id},
        )

    @server.tool(name="compare_runs")
    async def compare_runs(left_run_id: str, right_run_id: str) -> dict[str, object]:
        """Compare two tenant-scoped Runs."""

        return await control_plane.call_tool(
            principal=principal,
            name="compare_runs",
            arguments={"left_run_id": left_run_id, "right_run_id": right_run_id},
        )

    @server.tool(name="get_regression_summary")
    async def get_regression_summary(
        left_run_id: str,
        right_run_id: str,
        gate: dict[str, object],
    ) -> dict[str, object]:
        """Compare Agent evidence and apply caller-configured regression thresholds."""

        return await control_plane.call_tool(
            principal=principal,
            name="get_regression_summary",
            arguments={
                "left_run_id": left_run_id,
                "right_run_id": right_run_id,
                "gate": gate,
            },
        )

    return server
