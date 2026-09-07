"""Test-only real socket transport. Public DNS/peer identity is a fixture, not a TLS proof."""

import asyncio
import json
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from types import TracebackType
from typing import Any

import httpx

PUBLIC_FIXTURE_IP = "93.184.216.34"


class FixtureResolver:
    async def resolve(self, hostname: str) -> tuple[str, ...]:
        assert hostname == "rag.example.com"
        return (PUBLIC_FIXTURE_IP,)


class _FixturePeer:
    def get_extra_info(self, name: str) -> object:
        return (PUBLIC_FIXTURE_IP, 443) if name == "server_addr" else None


class LoopbackTargetTransport(httpx.AsyncBaseTransport):
    def __init__(self, port: int) -> None:
        if not 1 <= port <= 65535:
            raise ValueError("invalid fixture port")
        self._port = port
        self._transport = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        assert request.url.scheme == "https" and request.url.host == PUBLIC_FIXTURE_IP
        assert request.url.path == "/query" and request.method == "POST"
        forwarded = httpx.Request(
            "POST",
            f"http://127.0.0.1:{self._port}/query",
            headers=request.headers,
            content=await request.aread(),
            extensions={"timeout": request.extensions["timeout"]},
        )
        response = await self._transport.handle_async_request(forwarded)
        stream = response.extensions["network_stream"]
        peer = stream.get_extra_info("server_addr")
        assert peer[0] == "127.0.0.1" and peer[1] == self._port
        # Only injected test transport rewrites the claimed peer. Production code is unchanged.
        response.extensions["network_stream"] = _FixturePeer()
        return response

    async def aclose(self) -> None:
        await self._transport.aclose()


class LoopbackTargetService:
    def __init__(self, *, stall_body: bool = False) -> None:
        self.requests: list[dict[str, Any]] = []
        self.body_started = Event()
        self._release_body = Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1024 * 1024 or self.path != "/query":
                    self.send_error(400)
                    return
                body = json.loads(self.rfile.read(size))
                owner.requests.append(
                    {
                        "body": body,
                        "job_id": self.headers.get("X-EvalOps-Job-ID"),
                        "attempt": self.headers.get("X-EvalOps-Attempt"),
                    }
                )
                payload = json.dumps(
                    {
                        "answer": "private answer",
                        "citations": [{"source_id": "gold"}],
                        "trace": {
                            "cost_usd": 0.01,
                            "tool_calls": [],
                            "tool_error": False,
                            "terminal_state": "completed",
                            "budget_exhausted": False,
                        },
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                with suppress(BrokenPipeError, ConnectionResetError):
                    if stall_body:
                        self.wfile.write(payload[:1])
                        self.wfile.flush()
                        owner.body_started.set()
                        owner._release_body.wait(timeout=5)
                        self.wfile.write(payload[1:])
                    else:
                        self.wfile.write(payload)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_port
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    async def __aenter__(self) -> "LoopbackTargetService":
        self._thread.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._release_body.set()
        await asyncio.to_thread(self._server.shutdown)
        self._server.server_close()
        await asyncio.to_thread(self._thread.join, 5)
