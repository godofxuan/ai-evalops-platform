import re
from time import perf_counter
from uuid import uuid4

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger
from app.core.telemetry import Telemetry
from app.observability.metrics import PlatformMetrics

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _request_id_from(scope: Scope) -> str:
    candidate = Headers(scope=scope).get("x-request-id")
    if candidate is not None and _SAFE_REQUEST_ID.fullmatch(candidate):
        return candidate
    return str(uuid4())


class RequestContextMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        metrics: PlatformMetrics,
        telemetry: Telemetry,
    ) -> None:
        self._app = app
        self._logger = get_logger(__name__)
        self._metrics = metrics
        self._telemetry = telemetry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = _request_id_from(scope)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started_at = perf_counter()
        status_code = 500
        carrier = {
            key.decode("latin-1"): value.decode("latin-1")
            for key, value in scope.get("headers", ())
        }
        parent_context = self._telemetry.extract_context(carrier)

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        with self._telemetry.start_as_current_span(
            "api.request",
            attributes={
                "http.request.method": scope["method"],
                "url.path": scope["path"],
            },
            context=parent_context,
        ):
            trace_id = self._telemetry.current_trace_id()
            if trace_id is not None:
                structlog.contextvars.bind_contextvars(trace_id=trace_id)
            try:
                await self._app(scope, receive, send_with_request_id)
            except Exception:
                self._logger.error(
                    "http_request_failed",
                    method=scope["method"],
                    path=scope["path"],
                    duration_ms=round((perf_counter() - started_at) * 1000, 3),
                    outcome="error",
                    error_code="unhandled_exception",
                )
                raise
            else:
                self._logger.info(
                    "http_request_completed",
                    method=scope["method"],
                    path=scope["path"],
                    status_code=status_code,
                    duration_ms=round((perf_counter() - started_at) * 1000, 3),
                    outcome="success" if status_code < 500 else "error",
                )
            finally:
                duration_seconds = perf_counter() - started_at
                route = getattr(scope.get("route"), "path", "unmatched")
                self._metrics.observe_api_request(
                    method=scope["method"],
                    route=route,
                    status_code=status_code,
                    duration_seconds=duration_seconds,
                )
                structlog.contextvars.clear_contextvars()
