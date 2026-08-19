import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.errors import (
    APIError,
    handle_api_error,
    handle_dataset_name_conflict,
    handle_dataset_not_found,
    handle_dataset_validation_error,
    handle_duplicate_dataset_version,
    handle_idempotency_conflict,
    handle_invalid_evaluator_configuration,
    handle_invalid_target_configuration,
    handle_request_validation_error,
    handle_review_conflict,
    handle_review_not_found,
    handle_review_permission,
    handle_review_task_creation_permission,
    handle_run_not_found,
)
from app.api.middleware import RequestContextMiddleware
from app.api.routes_datasets import router as datasets_router
from app.api.routes_agent_artifacts import router as agent_artifacts_router
from app.api.routes_events import router as events_router
from app.api.routes_health import router as health_router
from app.api.routes_observability import router as observability_router
from app.api.routes_results import router as results_router
from app.api.routes_reviews import router as reviews_router
from app.api.routes_runs import router as runs_router
from app.agent_eval.service import SQLAlchemyAgentArtifactService
from app.artifacts.storage import build_artifact_store
from app.auth.repository import SQLAlchemyAPIKeyLookup
from app.core.config import Settings
from app.core.logging import configure_logging, get_logger
from app.core.telemetry import Telemetry, parse_otlp_headers
from app.datasets.service import (
    DatasetNameConflictError,
    DatasetNotFoundError,
    DuplicateDatasetVersionError,
    SQLAlchemyDatasetService,
)
from app.datasets.validation import DatasetValidationError, JSONLValidationLimits
from app.events.outbox import (
    OutboxDispatcher,
    SQLAlchemyOutboxMaintenance,
    SQLAlchemyOutboxStore,
    run_outbox_cleanup_loop,
    run_outbox_dispatch_loop,
)
from app.events.publisher import RedisEventPublisher
from app.events.sse import RunEventStream
from app.events.subscriber import RedisEventSubscriber
from app.health.service import (
    NotConfiguredReadinessProbe,
    ReadinessProbe,
    build_infrastructure_readiness_probe,
)
from app.jobs.cancellation import SQLAlchemyCancellationService
from app.observability.metrics import PlatformMetrics
from app.persistence.database import create_database_engine, create_session_factory
from app.persistence.redis import create_redis_client
from app.results.service import SQLAlchemyResultService
from app.reviews.service import (
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewPermissionError,
    ReviewTaskCreationPermissionError,
    SQLAlchemyReviewService,
)
from app.runs.repository import SQLAlchemyRunRepository
from app.runs.service import (
    IdempotencyConflictError,
    InvalidEvaluatorConfigurationError,
    InvalidTargetConfigurationError,
    RunDatasetVersionNotFoundError,
    RunNotFoundError,
    SQLAlchemyRunService,
)


def create_app(
    *,
    settings: Settings | None = None,
    readiness_probe: ReadinessProbe | None = None,
) -> FastAPI:
    runtime_settings = settings or Settings()
    configure_logging(log_level=runtime_settings.log_level)
    logger = get_logger(__name__)
    metrics = PlatformMetrics()
    telemetry = Telemetry(
        service_name=runtime_settings.otel_service_name,
        enabled=runtime_settings.otel_enabled,
        otlp_endpoint=runtime_settings.otel_exporter_otlp_endpoint,
        otlp_headers=parse_otlp_headers(
            None
            if runtime_settings.otel_exporter_otlp_headers is None
            else runtime_settings.otel_exporter_otlp_headers.get_secret_value()
        ),
        resource_attributes={"process.role": "api"},
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if readiness_probe is not None:
            try:
                yield
            finally:
                telemetry.shutdown()
            return

        engine = create_database_engine(runtime_settings)
        session_factory = create_session_factory(engine)
        redis_client = create_redis_client(runtime_settings)
        artifact_store = build_artifact_store(runtime_settings)
        application.state.database_engine = engine
        application.state.session_factory = session_factory
        application.state.api_key_lookup = SQLAlchemyAPIKeyLookup(session_factory)
        application.state.artifact_store = artifact_store
        application.state.dataset_service = SQLAlchemyDatasetService(
            session_factory=session_factory,
            artifact_store=artifact_store,
            validation_limits=JSONLValidationLimits(
                max_file_bytes=runtime_settings.dataset_max_file_bytes,
                max_cases=runtime_settings.dataset_max_cases,
                max_line_bytes=runtime_settings.dataset_max_line_bytes,
            ),
        )
        application.state.run_service = SQLAlchemyRunService(
            repository=SQLAlchemyRunRepository(session_factory),
            artifact_store=artifact_store,
            http_target_registry=runtime_settings.http_target_registry,
            metrics=metrics,
            telemetry=telemetry,
        )
        event_publisher = RedisEventPublisher(
            redis_client,
            metrics=metrics,
        )
        outbox_stop_requested = asyncio.Event()
        dispatcher_id = f"api:{uuid4().hex}"
        outbox_dispatcher = OutboxDispatcher(
            store=SQLAlchemyOutboxStore(
                session_factory,
                dispatcher_id=dispatcher_id,
                lease_seconds=runtime_settings.outbox_lease_seconds,
            ),
            publisher=event_publisher,
            publish_timeout_seconds=runtime_settings.outbox_publish_timeout_seconds,
            retry_base_seconds=runtime_settings.outbox_retry_base_seconds,
            retry_max_seconds=runtime_settings.outbox_retry_max_seconds,
            telemetry=telemetry,
            metrics=metrics,
        )
        outbox_dispatcher_task = asyncio.create_task(
            run_outbox_dispatch_loop(
                outbox_dispatcher,
                stop_requested=outbox_stop_requested,
                poll_seconds=runtime_settings.outbox_poll_seconds,
                batch_size=runtime_settings.outbox_batch_size,
            ),
            name="outbox-dispatcher",
        )
        outbox_maintenance = SQLAlchemyOutboxMaintenance(
            session_factory,
            retention_seconds=runtime_settings.outbox_retention_seconds,
        )
        outbox_cleanup_task = asyncio.create_task(
            run_outbox_cleanup_loop(
                outbox_maintenance,
                stop_requested=outbox_stop_requested,
                interval_seconds=runtime_settings.outbox_cleanup_interval_seconds,
                batch_size=runtime_settings.outbox_cleanup_batch_size,
                metrics=metrics,
            ),
            name="outbox-cleanup",
        )
        application.state.outbox_dispatcher = outbox_dispatcher
        application.state.outbox_dispatcher_task = outbox_dispatcher_task
        application.state.outbox_maintenance = outbox_maintenance
        application.state.outbox_cleanup_task = outbox_cleanup_task
        application.state.run_event_stream = RunEventStream(
            run_service=application.state.run_service,
            subscriber=RedisEventSubscriber(
                redis_client,
                poll_timeout_seconds=runtime_settings.sse_heartbeat_seconds,
            ),
            fallback_poll_seconds=runtime_settings.sse_fallback_poll_seconds,
            metrics=metrics,
            telemetry=telemetry,
        )
        application.state.cancellation_service = SQLAlchemyCancellationService(session_factory)
        application.state.result_service = SQLAlchemyResultService(
            session_factory,
            artifact_store=artifact_store,
        )
        application.state.review_service = SQLAlchemyReviewService(
            session_factory,
            artifact_store=artifact_store,
        )
        application.state.agent_artifact_service = SQLAlchemyAgentArtifactService(
            session_factory,
            artifact_store=artifact_store,
        )
        application.state.redis_client = redis_client
        application.state.readiness_probe = build_infrastructure_readiness_probe(
            settings=runtime_settings,
            engine=engine,
            redis_client=redis_client,
            artifact_store=artifact_store,
        )
        logger.info("application_started", environment=runtime_settings.environment)
        try:
            yield
        finally:
            outbox_stop_requested.set()
            try:
                await asyncio.gather(outbox_dispatcher_task, outbox_cleanup_task)
            finally:
                await redis_client.aclose()
                await engine.dispose()
                telemetry.shutdown()
                logger.info("application_stopped")

    application = FastAPI(
        title="AI EvalOps Platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = runtime_settings
    application.state.metrics = metrics
    application.state.telemetry = telemetry
    application.state.readiness_probe = readiness_probe or NotConfiguredReadinessProbe()
    application.state.api_key_lookup = None
    application.state.session_factory = None
    application.state.dataset_service = None
    application.state.run_service = None
    application.state.result_service = None
    application.state.review_service = None
    application.state.agent_artifact_service = None
    application.state.outbox_dispatcher = None
    application.state.outbox_dispatcher_task = None
    application.state.outbox_maintenance = None
    application.state.outbox_cleanup_task = None
    application.state.run_event_stream = None
    application.state.cancellation_service = None
    application.include_router(health_router)
    application.include_router(observability_router)
    application.include_router(datasets_router)
    application.include_router(agent_artifacts_router)
    application.include_router(results_router)
    application.include_router(reviews_router)
    application.include_router(runs_router)
    application.include_router(events_router)
    application.add_exception_handler(APIError, handle_api_error)
    application.add_exception_handler(DatasetNotFoundError, handle_dataset_not_found)
    application.add_exception_handler(
        DatasetNameConflictError,
        handle_dataset_name_conflict,
    )
    application.add_exception_handler(
        DuplicateDatasetVersionError,
        handle_duplicate_dataset_version,
    )
    application.add_exception_handler(
        IdempotencyConflictError,
        handle_idempotency_conflict,
    )
    application.add_exception_handler(
        InvalidEvaluatorConfigurationError,
        handle_invalid_evaluator_configuration,
    )
    application.add_exception_handler(
        InvalidTargetConfigurationError,
        handle_invalid_target_configuration,
    )
    application.add_exception_handler(RunNotFoundError, handle_run_not_found)
    application.add_exception_handler(ReviewNotFoundError, handle_review_not_found)
    application.add_exception_handler(ReviewPermissionError, handle_review_permission)
    application.add_exception_handler(
        ReviewTaskCreationPermissionError,
        handle_review_task_creation_permission,
    )
    application.add_exception_handler(ReviewConflictError, handle_review_conflict)
    application.add_exception_handler(
        RunDatasetVersionNotFoundError,
        handle_run_not_found,
    )
    application.add_exception_handler(
        DatasetValidationError,
        handle_dataset_validation_error,
    )
    application.add_exception_handler(
        RequestValidationError,
        handle_request_validation_error,
    )
    application.add_middleware(
        RequestContextMiddleware,
        metrics=metrics,
        telemetry=telemetry,
    )
    return application


app = create_app()
