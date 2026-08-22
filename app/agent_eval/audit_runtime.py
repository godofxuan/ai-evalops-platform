"""Standalone lifecycle for the credential-independent MCP audit dispatcher."""

import asyncio
import os
import socket
from uuid import uuid4

from app.agent_eval.audit_dispatcher import (
    AuditDispatcher,
    SQLAlchemyAuditEventSink,
    SQLAlchemyAuditOutboxStore,
    run_audit_dispatch_loop,
)
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.telemetry import Telemetry, parse_otlp_headers
from app.observability.metrics import PlatformMetrics, start_metrics_server
from app.persistence.database import create_database_engine, create_session_factory


async def run_audit_dispatcher_process(
    settings: Settings,
    *,
    stop_requested: asyncio.Event,
    once: bool = False,
) -> None:
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    dispatcher_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
    metrics = PlatformMetrics()
    telemetry = Telemetry(
        service_name=settings.otel_service_name,
        enabled=settings.otel_enabled,
        otlp_endpoint=settings.otel_exporter_otlp_endpoint,
        otlp_headers=parse_otlp_headers(
            None
            if settings.otel_exporter_otlp_headers is None
            else settings.otel_exporter_otlp_headers.get_secret_value()
        ),
        resource_attributes={
            "process.role": "mcp-audit-dispatcher",
            "service.instance.id": dispatcher_id,
        },
    )
    metrics_server = (
        start_metrics_server(
            metrics=metrics,
            host=settings.metrics_host,
            port=settings.audit_dispatcher_metrics_port,
        )
        if settings.metrics_enabled
        else None
    )
    dispatcher = AuditDispatcher(
        store=SQLAlchemyAuditOutboxStore(
            session_factory,
            dispatcher_id=dispatcher_id,
            lease_seconds=settings.audit_dispatcher_lease_seconds,
        ),
        sink=SQLAlchemyAuditEventSink(session_factory),
        delivery_timeout_seconds=settings.audit_dispatcher_delivery_timeout_seconds,
        retry_base_seconds=settings.audit_dispatcher_retry_base_seconds,
        retry_max_seconds=settings.audit_dispatcher_retry_max_seconds,
        metrics=metrics,
    )
    logger = get_logger(__name__, role="mcp_audit_dispatcher", dispatcher_id=dispatcher_id)
    logger.info("audit_dispatcher_started")
    try:
        if once:
            await dispatcher.dispatch_once(limit=settings.audit_dispatcher_batch_size)
        else:
            await run_audit_dispatch_loop(
                dispatcher,
                stop_requested=stop_requested,
                poll_seconds=settings.audit_dispatcher_poll_seconds,
                batch_size=settings.audit_dispatcher_batch_size,
            )
    finally:
        if metrics_server is not None:
            metrics_server.close()
        telemetry.shutdown()
        await engine.dispose()
        logger.info("audit_dispatcher_stopped")
