from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.middleware import RequestContextMiddleware
from app.api.routes_health import router as health_router
from app.core.config import Settings
from app.core.logging import configure_logging, get_logger
from app.health.service import (
    NotConfiguredReadinessProbe,
    ReadinessProbe,
    build_infrastructure_readiness_probe,
)
from app.persistence.database import create_database_engine
from app.persistence.redis import create_redis_client


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
        redis_client = create_redis_client(runtime_settings)
        application.state.database_engine = engine
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
    application.include_router(health_router)
    application.add_middleware(RequestContextMiddleware)
    return application


app = create_app()
