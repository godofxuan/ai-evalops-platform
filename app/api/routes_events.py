from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.auth.dependencies import get_principal
from app.auth.principals import Principal
from app.events.sse import RunEventStreamService

router = APIRouter(prefix="/api/v1/runs", tags=["run-events"])


@router.get("/{run_id}/events")
async def get_run_events(
    run_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> StreamingResponse:
    service = cast(RunEventStreamService | None, request.app.state.run_event_stream)
    if service is None:
        raise RuntimeError("run event stream is not configured")
    stream = await service.open(principal=principal, run_id=run_id)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
