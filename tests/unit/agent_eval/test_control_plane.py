from uuid import UUID

from app.agent_eval.control_plane import McpEvalControlPlane
from app.auth.principals import Principal

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
        return {"status": "accepted"}


async def test_mcp_control_plane_exposes_tools_and_preserves_principal_boundary() -> None:
    services = RecordingServices()
    control_plane = McpEvalControlPlane(services=services)

    result = await control_plane.call_tool(
        principal=PRINCIPAL,
        name="submit_evaluation",
        arguments={"idempotency_key": "agent-v1"},
    )

    assert result == {"status": "accepted"}
    assert services.called == (
        "submit_evaluation",
        PRINCIPAL,
        {"idempotency_key": "agent-v1"},
    )
    assert {item["name"] for item in control_plane.tool_definitions()} == {
        "submit_evaluation",
        "get_run_status",
        "list_failed_cases",
        "get_case_result",
        "get_case_trajectory",
        "compare_runs",
        "get_regression_summary",
    }
