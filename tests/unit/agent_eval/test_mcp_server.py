from uuid import UUID

from mcp import Client

from app.agent_eval.control_plane import McpEvalControlPlane
from app.agent_eval.mcp_server import build_mcp_server
from app.agent_eval.mcp_stdio import configured_mcp_api_key
from app.auth.principals import Principal
from app.core.config import Settings

PRINCIPAL = Principal(
    tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
    api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
    key_prefix="evk_001122334455",
)


class RecordingServices:
    def __init__(self) -> None:
        self.called: tuple[str, Principal, dict[str, object]] | None = None

    async def invoke(
        self,
        *,
        tool_name: str,
        principal: Principal,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        self.called = (tool_name, principal, arguments)
        return {"status": "running"}


async def test_official_mcp_server_lists_and_calls_authenticated_evalops_tools() -> None:
    services = RecordingServices()
    server = build_mcp_server(
        control_plane=McpEvalControlPlane(services=services),
        principal=PRINCIPAL,
    )

    async with Client(server) as client:
        tools = await client.list_tools()
        result = await client.call_tool(
            "get_run_status",
            {"run_id": "00000000-0000-0000-0000-000000000601"},
        )

    assert {tool.name for tool in tools.tools} == {
        "submit_evaluation",
        "get_run_status",
        "list_failed_cases",
        "get_case_result",
        "get_case_trajectory",
        "compare_runs",
        "get_regression_summary",
    }
    assert result.is_error is False
    assert services.called == (
        "get_run_status",
        PRINCIPAL,
        {"run_id": "00000000-0000-0000-0000-000000000601"},
    )


def test_stdio_server_fails_closed_without_a_configured_api_key() -> None:
    try:
        configured_mcp_api_key(Settings(_env_file=None, mcp_api_key=None))
    except RuntimeError as error:
        assert str(error) == "EVALOPS_MCP_API_KEY is required for the MCP stdio server"
    else:
        raise AssertionError("missing MCP credentials must fail closed")
