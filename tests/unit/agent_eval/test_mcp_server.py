from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from mcp import Client

from app.agent_eval.control_plane import McpEvalControlPlane
from app.agent_eval.mcp_server import build_mcp_server
from app.agent_eval.mcp_stdio import configured_mcp_api_key
from app.auth.principals import Principal
from app.auth.service import InvalidAPIKeyError
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


class RevocableAuthorizer:
    def __init__(self) -> None:
        self.calls = 0
        self.active = True

    @asynccontextmanager
    async def authorize(self, *, tool_name: str) -> AsyncIterator[Principal]:
        del tool_name
        self.calls += 1
        if not self.active:
            raise InvalidAPIKeyError
        yield PRINCIPAL


class RecordingAuditor:
    def __init__(self) -> None:
        self.records: list[tuple[UUID, str, str, str]] = []

    async def record(
        self,
        *,
        principal: Principal,
        tool_name: str,
        status: str,
        trace_id: str,
    ) -> None:
        self.records.append((principal.api_key_id, tool_name, status, trace_id))


async def test_official_mcp_server_lists_and_calls_authenticated_evalops_tools() -> None:
    services = RecordingServices()
    authorizer = RevocableAuthorizer()
    auditor = RecordingAuditor()
    server = build_mcp_server(
        control_plane=McpEvalControlPlane(services=services),
        authorizer=authorizer,
        auditor=auditor,
        credential_identity=PRINCIPAL,
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
    assert authorizer.calls == 1
    assert auditor.records[0][:3] == (
        PRINCIPAL.api_key_id,
        "get_run_status",
        "succeeded",
    )


async def test_mcp_reauthorizes_without_restart_and_audits_revocation_failure() -> None:
    services = RecordingServices()
    authorizer = RevocableAuthorizer()
    auditor = RecordingAuditor()
    server = build_mcp_server(
        control_plane=McpEvalControlPlane(services=services),
        authorizer=authorizer,
        auditor=auditor,
        credential_identity=PRINCIPAL,
    )

    async with Client(server) as client:
        first = await client.call_tool(
            "get_run_status",
            {"run_id": "00000000-0000-0000-0000-000000000601"},
        )
        authorizer.active = False
        second = await client.call_tool(
            "get_run_status",
            {"run_id": "00000000-0000-0000-0000-000000000601"},
        )

    assert first.is_error is False
    assert second.is_error is True
    assert authorizer.calls == 2
    assert [record[2] for record in auditor.records] == ["succeeded", "failed"]


def test_stdio_server_fails_closed_without_a_configured_api_key() -> None:
    try:
        configured_mcp_api_key(Settings(_env_file=None, mcp_api_key=None))
    except RuntimeError as error:
        assert str(error) == "EVALOPS_MCP_API_KEY is required for the MCP stdio server"
    else:
        raise AssertionError("missing MCP credentials must fail closed")
