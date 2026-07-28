from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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
    handle_run_not_found,
)
from app.api.middleware import RequestContextMiddleware
from app.api.routes_datasets import router as datasets_router
from app.api.routes_events import router as events_router
from app.api.routes_health import router as health_router
from app.api.routes_runs import router as runs_router
from app.artifacts.storage import LocalArtifactStore
from app.auth.repository import SQLAlchemyAPIKeyLookup
from app.core.config import Settings
from app.core.logging import configure_logging, get_logger
from app.datasets.service import (
    DatasetNameConflictError,
    DatasetNotFoundError,
    DuplicateDatasetVersionError,
    SQLAlchemyDatasetService,
)
from app.datasets.validation import DatasetValidationError, JSONLValidationLimits
from app.events.publisher import RedisEventPublisher
from app.events.sse import RunEventStream
from app.events.subscriber import RedisEventSubscriber
from app.health.service import (
    NotConfiguredReadinessProbe,
    ReadinessProbe,
    build_infrastructure_readiness_probe,
)
from app.jobs.cancellation import SQLAlchemyCancellationService
from app.persistence.database import create_database_engine, create_session_factory
from app.persistence.redis import create_redis_client
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

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if readiness_probe is not None:
            yield
            return

        runtime_settings.artifact_root.mkdir(parents=True, exist_ok=True)
        engine = create_database_engine(runtime_settings)
        session_factory = create_session_factory(engine)
        redis_client = create_redis_client(runtime_settings)
        artifact_store = LocalArtifactStore(runtime_settings.artifact_root)
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
        )
        application.state.event_publisher = RedisEventPublisher(redis_client)
        application.state.run_event_stream = RunEventStream(
            run_service=application.state.run_service,
            subscriber=RedisEventSubscriber(
                redis_client,
                poll_timeout_seconds=runtime_settings.sse_heartbeat_seconds,
            ),
            fallback_poll_seconds=runtime_settings.sse_fallback_poll_seconds,
        )
        application.state.cancellation_service = SQLAlchemyCancellationService(session_factory)
        application.state.redis_client = redis_client
        application.state.readiness_probe = build_infrastructure_readiness_probe(
            settings=runtime_settings,
            engine=engine,
            redis_client=redis_client,
        )
        logger.info("application_started", environment=runtime_settings.environment)
        try:
            yield
        finally:
            await redis_client.aclose()
            await engine.dispose()
            logger.info("application_stopped")

    application = FastAPI(
        title="AI EvalOps Platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = runtime_settings
    application.state.readiness_probe = readiness_probe or NotConfiguredReadinessProbe()
    application.state.api_key_lookup = None
    application.state.dataset_service = None
    application.state.run_service = None
    application.state.event_publisher = None
    application.state.run_event_stream = None
    application.state.cancellation_service = None
    application.include_router(health_router)
    application.include_router(datasets_router)
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
    application.add_middleware(RequestContextMiddleware)
    return application


app = create_app()
