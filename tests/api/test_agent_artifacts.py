from datetime import UTC, datetime
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.agent_eval.schemas import AgentArtifactRead, AgentArtifactUpload
from app.agent_eval.service import AgentArtifactRunMismatchError
from app.auth.dependencies import get_principal
from app.auth.principals import Principal
from app.core.telemetry import Telemetry
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


async def test_agent_artifact_run_mismatch_is_a_safe_validation_error() -> None:
    class MismatchService(RecordingAgentArtifactService):
        async def ingest(
            self,
            *,
            principal: Principal,
            run_id: UUID,
            request: AgentArtifactUpload,
        ) -> AgentArtifactRead:
            raise AgentArtifactRunMismatchError("mismatch")

    application = create_app()
    application.dependency_overrides[get_principal] = lambda: PRINCIPAL
    application.state.agent_artifact_service = MismatchService()
    async with AsyncClient(
        transport=ASGITransport(app=application, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/v1/runs/{RUN_ID}/agent-artifacts", json=_payload())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_agent_artifact"


async def test_agent_artifact_ingestion_records_safe_correlation_span() -> None:
    exporter = InMemorySpanExporter()
    telemetry = Telemetry(
        service_name="evalops-agent-artifact-test",
        span_processors=(SimpleSpanProcessor(exporter),),
    )
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: PRINCIPAL
    application.state.agent_artifact_service = RecordingAgentArtifactService()
    application.state.telemetry = telemetry
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/v1/runs/{RUN_ID}/agent-artifacts", json=_payload())

    assert response.status_code == 201
    span = next(
        item for item in exporter.get_finished_spans() if item.name == "agent_artifact.ingest"
    )
    assert span.attributes is not None
    assert span.attributes["agent.framework"] == "custom-controller"
    assert span.attributes["eval.case_id"] == "case-001"
    assert "find the handbook" not in span.attributes.values()
