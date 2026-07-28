import asyncio
import ipaddress
import os
import socket
import time
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.domain.evaluation import (
    EvaluationCase,
    ExecutionContext,
    TargetResult,
    TokenUsage,
)
from app.targets.base import (
    InvalidTargetConfiguration,
    TargetCancelledError,
    TargetExecutionError,
    TargetHTTPError,
    TargetInvalidResponseError,
    TargetTimeoutError,
)


class HostResolver(Protocol):
    async def resolve(self, hostname: str) -> tuple[str, ...]:
        """Resolve all current addresses for a target hostname."""


class SystemHostResolver:
    async def resolve(self, hostname: str) -> tuple[str, ...]:
        loop = asyncio.get_running_loop()
        records = await loop.getaddrinfo(
            hostname,
            None,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
        return tuple(sorted({str(record[4][0]) for record in records}))


class HTTPRAGTargetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=1, max_length=2_048)
    endpoint: str = Field(min_length=1, max_length=1_024)
    allowed_hosts: list[str] = Field(min_length=1, max_length=20)
    auth_env_var: str | None = Field(
        default=None,
        pattern=r"^[A-Z][A-Z0-9_]{0,127}$",
    )
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    request_question_field: str = Field(default="question", min_length=1, max_length=100)
    answer_path: str = Field(default="answer", min_length=1, max_length=200)
    citations_path: str = Field(default="citations", min_length=1, max_length=200)
    sources_path: str = Field(default="sources", min_length=1, max_length=200)
    trace_path: str = Field(default="trace", min_length=1, max_length=200)
    usage_path: str = Field(default="usage", min_length=1, max_length=200)
    include_metadata: bool = False

    @field_validator("allowed_hosts")
    @classmethod
    def normalize_allowed_hosts(cls, hosts: list[str]) -> list[str]:
        normalized = [host.rstrip(".").casefold() for host in hosts]
        if any(
            not host or host == "localhost" or _is_non_public_ip_literal(host)
            for host in normalized
        ):
            raise ValueError("allowed_hosts may not contain local or non-public hosts")
        if len(set(normalized)) != len(normalized):
            raise ValueError("allowed_hosts contains duplicates")
        return normalized


class HTTPRAGTarget:
    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        client: httpx.AsyncClient | None = None,
        resolver: HostResolver | None = None,
    ) -> None:
        try:
            parsed = HTTPRAGTargetConfig.model_validate(dict(config))
            url = _validate_and_build_url(parsed)
        except (ValidationError, ValueError) as error:
            raise InvalidTargetConfiguration(
                "unsafe or invalid HTTP target configuration"
            ) from error
        self._config = parsed
        self._url = url
        self._client = client
        self._resolver = resolver or SystemHostResolver()

    async def execute_case(
        self,
        case: EvaluationCase,
        context: ExecutionContext,
    ) -> TargetResult:
        if context.cancellation.is_set():
            raise TargetCancelledError
        hostname = self._url.host
        if hostname is None:
            raise InvalidTargetConfiguration("target URL has no hostname")
        addresses = await self._resolver.resolve(hostname)
        _require_public_addresses(addresses)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-EvalOps-Job-ID": str(context.job_id),
            "X-EvalOps-Attempt": str(context.attempt_number),
        }
        if self._config.auth_env_var is not None:
            token = os.getenv(self._config.auth_env_var)
            if token is None or not token:
                raise InvalidTargetConfiguration("configured target credential is unavailable")
            headers["Authorization"] = f"Bearer {token}"
        payload: dict[str, Any] = {
            self._config.request_question_field: case.question,
        }
        if self._config.include_metadata:
            payload["metadata"] = case.metadata

        started = time.perf_counter()
        try:
            response = await self._post(payload=payload, headers=headers)
        except httpx.TimeoutException:
            raise TargetTimeoutError from None
        except httpx.RequestError:
            raise TargetExecutionError(
                "target_connection_error",
                "target connection failed",
                retryable=True,
            ) from None
        latency_ms = max(0, int((time.perf_counter() - started) * 1_000))
        if context.cancellation.is_set():
            raise TargetCancelledError
        if response.status_code >= 400:
            raise TargetHTTPError(response.status_code)
        try:
            body = response.json()
        except ValueError:
            raise TargetInvalidResponseError("target_invalid_json") from None
        if not isinstance(body, dict):
            raise TargetInvalidResponseError
        answer = _extract(body, self._config.answer_path)
        citations = _extract(body, self._config.citations_path, default=[])
        sources = _extract(body, self._config.sources_path, default=[])
        trace = _extract(body, self._config.trace_path, default={})
        usage = _extract(body, self._config.usage_path, default=None)
        return TargetResult(
            answer=_optional_string(answer),
            citations=_object_tuple(citations, field="citations"),
            sources=_object_tuple(sources, field="sources"),
            trace=_object_mapping(trace, field="trace"),
            token_usage=_token_usage(usage),
            latency_ms=latency_ms,
        )

    async def _post(
        self,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> httpx.Response:
        if self._client is not None:
            return await self._client.post(
                self._url,
                json=payload,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        async with httpx.AsyncClient() as client:
            return await client.post(
                self._url,
                json=payload,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )


def _validate_and_build_url(config: HTTPRAGTargetConfig) -> httpx.URL:
    base = urlsplit(config.base_url)
    if (
        base.scheme != "https"
        or base.hostname is None
        or base.username is not None
        or base.password is not None
        or base.query
        or base.fragment
    ):
        raise ValueError("base_url must be a credential-free HTTPS origin or base path")
    hostname = base.hostname.rstrip(".").casefold()
    if hostname not in config.allowed_hosts:
        raise ValueError("base_url hostname is outside allowed_hosts")
    endpoint = urlsplit(config.endpoint)
    if (
        not config.endpoint.startswith("/")
        or config.endpoint.startswith("//")
        or endpoint.scheme
        or endpoint.netloc
        or endpoint.query
        or endpoint.fragment
    ):
        raise ValueError("endpoint must be an absolute path without authority or query")
    return httpx.URL(config.base_url.rstrip("/") + config.endpoint)


def _is_non_public_ip_literal(hostname: str) -> bool:
    try:
        return not ipaddress.ip_address(hostname).is_global
    except ValueError:
        return False


def _require_public_addresses(addresses: tuple[str, ...]) -> None:
    if not addresses:
        raise InvalidTargetConfiguration("target hostname did not resolve")
    try:
        parsed = tuple(ipaddress.ip_address(address) for address in addresses)
    except ValueError as error:
        raise InvalidTargetConfiguration("target resolver returned an invalid address") from error
    if any(not address.is_global for address in parsed):
        raise InvalidTargetConfiguration("target hostname must resolve only to public addresses")


_MISSING = object()


def _extract(body: dict[str, Any], path: str, *, default: object = _MISSING) -> Any:
    current: Any = body
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            if default is not _MISSING:
                return default
            raise TargetInvalidResponseError("target_response_mapping_error")
        current = current[part]
    return current


def _optional_string(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise TargetInvalidResponseError("target_answer_type_error")


def _object_tuple(value: Any, *, field: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise TargetInvalidResponseError(f"target_{field}_type_error")
    return tuple(dict(item) for item in value)


def _object_mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TargetInvalidResponseError(f"target_{field}_type_error")
    return dict(value)


def _token_usage(value: Any) -> TokenUsage | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TargetInvalidResponseError("target_usage_type_error")
    input_tokens = value.get("input_tokens")
    output_tokens = value.get("output_tokens")
    if (
        isinstance(input_tokens, bool)
        or not isinstance(input_tokens, int)
        or isinstance(output_tokens, bool)
        or not isinstance(output_tokens, int)
    ):
        raise TargetInvalidResponseError("target_usage_type_error")
    try:
        return TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens)
    except ValueError:
        raise TargetInvalidResponseError("target_usage_type_error") from None
