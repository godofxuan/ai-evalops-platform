"""Bounded authenticated client for recovering durable experiments by their ID."""

import asyncio
import base64
import hashlib
import json
import math
import re
from types import TracebackType
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from app.core.strict_json import decode_evidence_json
from app.datasets.schemas import DatasetCreate, DatasetRead, DatasetVersionRead
from app.product_experiments.durable_verification import verify_durable_report
from app.product_experiments.service import (
    ExperimentSubmissionAccepted,
    ProductExperimentRead,
    ProductState,
)
from app.product_experiments.submission import DurableExperimentRequest


class ProductAPIError(RuntimeError):
    """Safe code only: upstream bodies and credentials are never error messages."""


class ProductWaitTimeout(ProductAPIError):
    def __init__(self, experiment_id: UUID, last_observed_state: ProductState | None) -> None:
        super().__init__("api_wait_timeout")
        self.experiment_id = experiment_id
        self.last_observed_state = last_observed_state


class ProductAPIClient:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        *,
        http: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30,
        max_response_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        try:
            url = urlsplit(api_url)
            valid = (
                url.scheme in {"https", "http"}
                and bool(url.hostname)
                and url.username is None
                and url.password is None
                and not url.query
                and not url.fragment
                and url.path in {"", "/"}
                and (url.scheme == "https" or url.hostname in {"localhost", "127.0.0.1", "::1"})
            )
            _ = url.port
        except ValueError:
            valid = False
        if not valid or any(character.isspace() for character in api_url):
            raise ValueError("invalid_api_url")
        if not api_key or not api_key.isascii() or any(c.isspace() for c in api_key):
            raise ValueError("invalid_api_key")
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300:
            raise ValueError("invalid_request_timeout")
        if not 1 <= max_response_bytes <= 512 * 1024 * 1024:
            raise ValueError("invalid_response_limit")
        self._base = api_url.rstrip("/")
        self._key = api_key
        self._timeout = timeout_seconds
        self._limit = max_response_bytes
        self._owned = http is None
        self._http = http if http is not None else httpx.AsyncClient(trust_env=False)

    async def __aenter__(self) -> "ProductAPIClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._owned:
            await self._http.aclose()

    async def get(self, experiment_id: UUID) -> ProductExperimentRead:
        return await self._control(experiment_id, "GET", "", 200)

    async def create_dataset(self, *, name: str) -> DatasetRead:
        request = DatasetCreate(name=name)
        body = await self._request(
            "POST",
            "/api/v1/datasets",
            201,
            content=request.model_dump_json().encode(),
            extra_headers={"Content-Type": "application/json"},
        )
        try:
            return DatasetRead.model_validate_json(body)
        except ValueError:
            raise ProductAPIError("api_dataset_response_invalid") from None

    async def upload_dataset_version(self, dataset_id: UUID, payload: bytes) -> DatasetVersionRead:
        if not isinstance(dataset_id, UUID) or not 0 < len(payload) <= 10 * 1024 * 1024:
            raise ValueError("invalid_dataset_upload")
        body = await self._request(
            "POST",
            f"/api/v1/datasets/{dataset_id}/versions",
            201,
            files={"file": ("normalized.jsonl", payload, "application/x-ndjson")},
        )
        try:
            version = DatasetVersionRead.model_validate_json(body)
        except ValueError:
            raise ProductAPIError("api_dataset_response_invalid") from None
        if (
            version.dataset_id != dataset_id
            or version.sha256 != hashlib.sha256(payload).hexdigest()
        ):
            raise ProductAPIError("api_dataset_identity")
        return version

    async def submit(
        self, *, request: DurableExperimentRequest, dataset_payload: bytes, idempotency_key: str
    ) -> ExperimentSubmissionAccepted:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", idempotency_key):
            raise ValueError("invalid_idempotency_key")
        request = DurableExperimentRequest.model_validate_json(request.model_dump_json())
        if not 0 < len(dataset_payload) <= 10 * 1024 * 1024:
            raise ValueError("invalid_dataset_size")
        if hashlib.sha256(dataset_payload).hexdigest() != request.source_dataset_sha256:
            raise ValueError("dataset_hash_mismatch")
        if len(request.model_dump_json().encode("utf-8")) > 1024 * 1024:
            raise ValueError("invalid_request_size")
        payload = json.dumps(
            {
                "request": request.model_dump(mode="json"),
                "dataset_base64": base64.b64encode(dataset_payload).decode("ascii"),
            },
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if len(payload) > 16 * 1024 * 1024:
            raise ValueError("invalid_submission_size")
        body = await self._request(
            "POST",
            "/api/v1/experiments",
            202,
            content=payload,
            extra_headers={"Idempotency-Key": idempotency_key, "Content-Type": "application/json"},
        )
        try:
            accepted = ExperimentSubmissionAccepted.model_validate_json(body)
            if (
                accepted.baseline_run_id == accepted.candidate_run_id
                or accepted.status_url != f"/api/v1/experiments/{accepted.id}"
            ):
                raise ValueError("invalid_submission_identity")
            return accepted
        except ValueError:
            raise ProductAPIError("api_response_invalid") from None

    async def cancel(self, experiment_id: UUID) -> ProductExperimentRead:
        return await self._control(experiment_id, "POST", "/cancel", 202)

    async def export(self, experiment_id: UUID, *, include_private: bool = False) -> bytes:
        if not isinstance(experiment_id, UUID):
            raise ValueError("invalid_experiment_id")
        path = f"/api/v1/experiments/{experiment_id}/export"
        if include_private:
            path += "?include_private=true"
        payload = await self._request("POST", path, 200)
        try:
            verified = verify_durable_report(payload, experiment_id=experiment_id)
        except ValueError:
            raise ProductAPIError("api_export_invalid") from None
        is_public = verified.verification_scope == "PUBLIC_PROJECTION_ONLY"
        if is_public == include_private:
            raise ProductAPIError("api_export_visibility")
        return payload

    async def wait(
        self, experiment_id: UUID, *, wait_seconds: float = 300, poll_seconds: float = 2
    ) -> ProductExperimentRead:
        """Wait locally; a timeout or interrupted caller never cancels the server job."""
        if not math.isfinite(wait_seconds) or not 0 < wait_seconds <= 86400:
            raise ValueError("invalid_wait_timeout")
        if not math.isfinite(poll_seconds) or not 0 < poll_seconds <= 60:
            raise ValueError("invalid_poll_interval")
        last_observed_state: ProductState | None = None
        try:
            async with asyncio.timeout(wait_seconds):
                while True:
                    result = await self.get(experiment_id)
                    last_observed_state = result.state
                    if result.state in {"READY_FOR_ASSESSMENT", "EXECUTION_FAILED", "CANCELLED"}:
                        return result
                    await asyncio.sleep(poll_seconds)
        except TimeoutError:
            raise ProductWaitTimeout(experiment_id, last_observed_state) from None

    async def _control(
        self, experiment_id: UUID, method: str, suffix: str, expected_status: int
    ) -> ProductExperimentRead:
        if not isinstance(experiment_id, UUID):
            raise ValueError("invalid_experiment_id")
        body = await self._request(
            method, f"/api/v1/experiments/{experiment_id}{suffix}", expected_status
        )
        try:
            result = ProductExperimentRead.model_validate_json(body)
            if result.id != experiment_id:
                raise ProductAPIError("api_experiment_identity")
            return result
        except ValueError:
            raise ProductAPIError("api_response_invalid") from None

    async def _request(
        self,
        method: str,
        path: str,
        expected_status: int,
        *,
        content: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> bytes:
        try:
            async with asyncio.timeout(self._timeout):
                async with self._http.stream(
                    method,
                    f"{self._base}{path}",
                    headers={
                        "Authorization": f"Bearer {self._key}",
                        "Accept-Encoding": "identity",
                        **(extra_headers or {}),
                    },
                    content=content,
                    files=files,
                    follow_redirects=False,
                    timeout=self._timeout,
                ) as response:
                    if response.status_code != expected_status:
                        raise ProductAPIError(f"api_http_{response.status_code}")
                    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                        raise ProductAPIError("api_response_encoding")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > self._limit:
                            raise ProductAPIError("api_response_limit")
                        body.extend(chunk)
            decode_evidence_json(bytes(body))
            return bytes(body)
        except (httpx.HTTPError, TimeoutError):
            raise ProductAPIError("api_transport_error") from None
        except ValueError:
            raise ProductAPIError("api_response_invalid") from None
