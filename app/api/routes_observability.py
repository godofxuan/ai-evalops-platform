from contextlib import suppress
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.observability.durable import refresh_durable_job_gauges
from app.observability.metrics import PlatformMetrics
from app.persistence.database import AsyncSessionFactory

router = APIRouter(tags=["observability"])


@router.get("/metrics", include_in_schema=False)
async def get_metrics(request: Request) -> Response:
    if not request.app.state.settings.metrics_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    metrics = cast(PlatformMetrics, request.app.state.metrics)
    session_factory = cast(
        AsyncSessionFactory | None,
        request.app.state.session_factory,
    )
    if session_factory is not None:
        with suppress(Exception):
            await refresh_durable_job_gauges(
                session_factory=session_factory,
                metrics=metrics,
                now=datetime.now(UTC),
            )
    return Response(
        content=metrics.render(),
        headers={"Content-Type": metrics.content_type},
    )
