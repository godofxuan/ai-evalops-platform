"""Fail-closed stdio entry point for the official MCP SDK server."""

from datetime import UTC, datetime

from app.agent_eval.control_plane import McpEvalControlPlane
from app.agent_eval.mcp_server import build_mcp_server
from app.agent_eval.mcp_service_adapter import EvalOpsMcpServiceAdapter
from app.agent_eval.regression_service import SQLAlchemyAgentRegressionService
from app.agent_eval.service import SQLAlchemyAgentArtifactService
from app.artifacts.storage import build_artifact_store
from app.auth.repository import SQLAlchemyAPIKeyLookup
from app.auth.service import authenticate_api_key
from app.core.config import Settings
from app.core.event_loop import run_with_psycopg_compatible_event_loop
from app.core.telemetry import Telemetry, parse_otlp_headers
from app.persistence.database import create_database_engine, create_session_factory
from app.results.service import SQLAlchemyResultService
from app.runs.repository import SQLAlchemyRunRepository
from app.runs.service import SQLAlchemyRunService


def configured_mcp_api_key(settings: Settings) -> str:
    if settings.mcp_api_key is None:
        raise RuntimeError("EVALOPS_MCP_API_KEY is required for the MCP stdio server")
    return settings.mcp_api_key.get_secret_value()


async def run_stdio(settings: Settings | None = None) -> None:
    runtime_settings = settings or Settings()
    plaintext_api_key = configured_mcp_api_key(runtime_settings)
    engine = create_database_engine(runtime_settings)
    session_factory = create_session_factory(engine)
    artifact_store = build_artifact_store(runtime_settings)
    telemetry = Telemetry(
        service_name=runtime_settings.otel_service_name,
        enabled=runtime_settings.otel_enabled,
        otlp_endpoint=runtime_settings.otel_exporter_otlp_endpoint,
        otlp_headers=parse_otlp_headers(
            None
            if runtime_settings.otel_exporter_otlp_headers is None
            else runtime_settings.otel_exporter_otlp_headers.get_secret_value()
        ),
        resource_attributes={"process.role": "mcp-stdio"},
    )
    try:
        principal = await authenticate_api_key(
            plaintext_api_key,
            lookup=SQLAlchemyAPIKeyLookup(session_factory),
            now=datetime.now(UTC),
        )
        run_service = SQLAlchemyRunService(
            repository=SQLAlchemyRunRepository(session_factory),
            artifact_store=artifact_store,
            http_target_registry=runtime_settings.http_target_registry,
            telemetry=telemetry,
        )
        result_service = SQLAlchemyResultService(
            session_factory,
            artifact_store=artifact_store,
        )
        agent_artifact_service = SQLAlchemyAgentArtifactService(
            session_factory,
            artifact_store=artifact_store,
        )
        agent_regression_service = SQLAlchemyAgentRegressionService(session_factory)
        services = EvalOpsMcpServiceAdapter(
            run_service=run_service,
            result_service=result_service,
            agent_artifact_service=agent_artifact_service,
            agent_regression_service=agent_regression_service,
        )
        server = build_mcp_server(
            control_plane=McpEvalControlPlane(services=services),
            principal=principal,
        )
        await server.run_stdio_async()
    finally:
        await engine.dispose()
        telemetry.shutdown()


def main() -> None:
    run_with_psycopg_compatible_event_loop(run_stdio())


if __name__ == "__main__":
    main()
