"""Bounded, strict decoding of an authenticated experiment submission."""

import asyncio
import base64
from typing import Any, cast

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.errors import APIError
from app.core.strict_json import decode_evidence_json
from app.product_experiments.submission import DurableExperimentRequest

MAX_SUBMISSION_BYTES = 16 * 1024 * 1024


class ExperimentSubmissionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request: DurableExperimentRequest
    dataset_base64: str = Field(min_length=1, max_length=14 * 1024 * 1024)


def experiment_submission_schema() -> dict[str, Any]:
    """Inline this controlled, acyclic schema so nested $defs resolve in OpenAPI."""
    root = ExperimentSubmissionEnvelope.model_json_schema()
    definitions = root.pop("$defs", {})

    def expand(node: Any, ancestors: tuple[str, ...] = ()) -> Any:
        if isinstance(node, list):
            return [expand(value, ancestors) for value in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            reference = node["$ref"]
            if not reference.startswith("#/$defs/") or reference in ancestors:
                raise ValueError("submission schema must have acyclic local definitions")
            resolved = expand(
                definitions[reference.removeprefix("#/$defs/")], (*ancestors, reference)
            )
            return {
                **resolved,
                **{key: expand(value, ancestors) for key, value in node.items() if key != "$ref"},
            }
        return {key: expand(value, ancestors) for key, value in node.items()}

    return cast(dict[str, Any], expand(root))


async def read_experiment_submission(request: Request) -> tuple[DurableExperimentRequest, bytes]:
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        raise APIError(415, "unsupported_media_type", "Use application/json.")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise APIError(
            415, "unsupported_content_encoding", "Compressed submissions are not supported."
        )
    raw_length = request.headers.get("content-length")
    if raw_length is not None:
        if len(raw_length) > 10 or not raw_length.isascii() or not raw_length.isdigit():
            raise APIError(400, "invalid_content_length", "Content length is invalid.")
        if int(raw_length) > MAX_SUBMISSION_BYTES:
            raise APIError(
                413, "submission_too_large", "Experiment submission exceeds the size limit."
            )
    content = bytearray()
    try:
        async with asyncio.timeout(10):
            async for chunk in request.stream():
                if len(content) + len(chunk) > MAX_SUBMISSION_BYTES:
                    raise APIError(
                        413, "submission_too_large", "Experiment submission exceeds the size limit."
                    )
                content.extend(chunk)
    except TimeoutError:
        raise APIError(408, "submission_timeout", "Experiment submission timed out.") from None
    try:
        payload = bytes(content)
        decode_evidence_json(payload)
        envelope = ExperimentSubmissionEnvelope.model_validate_json(payload)
        if len(envelope.request.model_dump_json().encode("utf-8")) > 1024 * 1024:
            raise ValueError("control request too large")
        dataset = base64.b64decode(envelope.dataset_base64, validate=True)
        if len(dataset) > 10 * 1024 * 1024:
            raise ValueError("source dataset too large")
    except ValueError:
        raise APIError(
            422, "invalid_experiment_submission", "Experiment submission is invalid."
        ) from None
    return envelope.request, dataset
