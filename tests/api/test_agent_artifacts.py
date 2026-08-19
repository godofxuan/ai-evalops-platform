from datetime import UTC, datetime
from uuid import UUID

from httpx import ASGITransport, AsyncClient

from app.agent_eval.schemas import AgentArtifactRead, AgentArtifactUpload
from app.auth.dependencies import get_principal
from app.auth.principals import Principal
from app.main import create_app

PRINCIPAL = Principal(
    tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
    api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
    key_prefix="evk_001122334455",
)
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")


def _payload() -> dict[str, object]:
    return {
        "artifact": {
            "schema_version": "agent-run-artifact/v1",
            "run_id": str(RUN_ID),
            "case_id": "case-001",
            "session_id": "session-001",
            "framework": "custom-controller",
            "input": {"message": "find the handbook"},
            "output": {"answer": "engineering drive"},
            "trajectory": [
                {
                    "event_id": "event-001",
                    "event_type": "tool_call",
                    "tool_name": "search_documents",
                    "payload": {},
                }
            ],
            "terminal": {"state": "answer"},
        }
    }


class RecordingAgentArtifactService:
    def __init__(self) -> None:
        self.called_with: tuple[Principal, UUID, AgentArtifactUpload] | None = None

    async def ingest(
        self,
        *,
        principal: Principal,
        run_id: UUID,
        request: AgentArtifactUpload,
    ) -> AgentArtifactRead:
        self.called_with = (principal, run_id, request)
        artifact = request.artifact
        return AgentArtifactRead(
            id=UUID("00000000-0000-0000-0000-000000000701"),
            run_id=run_id,
            case_id=artifact.case_id,
            schema_version=artifact.schema_version,
            framework=artifact.framework,
            content_sha256="a" * 64,
            terminal_state="answer",
            created_at=datetime(2026, 8, 19, tzinfo=UTC),
        )


async def test_agent_artifact_ingestion_uses_server_derived_tenant_principal() -> None:
    service = RecordingAgentArtifactService()
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: PRINCIPAL
    application.state.agent_artifact_service = service

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/v1/runs/{RUN_ID}/agent-artifacts", json=_payload())

    assert response.status_code == 201
    assert response.json()["case_id"] == "case-001"
    assert service.called_with is not None
    principal, run_id, request = service.called_with
    assert principal == PRINCIPAL
    assert run_id == RUN_ID
    assert request.artifact.framework == "custom-controller"
