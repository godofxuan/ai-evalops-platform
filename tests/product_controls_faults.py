"""Database-backed product controls: lost acknowledgement replay and cooperative cancel race."""

import asyncio
import base64
import json
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from app.domain.evaluation import EvaluationCase, TargetResult
from app.evaluators.base import build_evaluator
from app.jobs.claiming import SQLAlchemyJobClaimer
from app.jobs.lease import LeasePolicy
from app.jobs.results import SQLAlchemyResultCommitter
from app.persistence.database import AsyncSessionFactory
from app.product_experiments.client import ProductAPIClient, ProductAPIError
from app.product_experiments.durable_verification import verify_durable_report
from app.product_experiments.submission import DurableExperimentRequest


async def exercise_product_control_faults(
    application: FastAPI, api: httpx.AsyncClient, headers: dict[str, str], payload: dict[str, Any]
) -> None:
    class LostAcknowledgement(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.inner = httpx.ASGITransport(app=application)
            self.lost_id: UUID | None = None

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            response = await self.inner.handle_async_request(request)
            if (
                self.lost_id is None
                and request.url.path == "/api/v1/experiments"
                and response.status_code == 202
            ):
                body = await response.aread()
                self.lost_id = UUID(json.loads(body)["id"])
                await response.aclose()
                raise httpx.ReadError("synthetic_acknowledgement_lost", request=request)
            return response

        async def aclose(self) -> None:
            await self.inner.aclose()

    transport = LostAcknowledgement()
    key = headers["Authorization"].removeprefix("Bearer ")
    raw = base64.b64decode(payload["dataset_base64"], validate=True)
    request = DurableExperimentRequest.model_validate_json(json.dumps(payload["request"]))
    async with (
        httpx.AsyncClient(transport=transport) as http,
        ProductAPIClient("https://evalops.example", key, http=http) as sdk,
    ):
        with pytest.raises(ProductAPIError, match="^api_transport_error$"):
            await sdk.submit(
                request=request, dataset_payload=raw, idempotency_key="lost-submit-response"
            )
        accepted = await sdk.submit(
            request=request, dataset_payload=raw, idempotency_key="lost-submit-response"
        )
        assert accepted.id == transport.lost_id
        assert (await sdk.cancel(accepted.id)).state == "CANCELLED"

    async with ProductAPIClient("https://evalops.example", key, http=api) as sdk:
        accepted = await sdk.submit(
            request=request, dataset_payload=raw, idempotency_key="parent-cancel-race"
        )
        factory = cast(AsyncSessionFactory, application.state.session_factory)
        claimer = SQLAlchemyJobClaimer(factory, lease_policy=LeasePolicy(timedelta(seconds=60)))
        claim = (await claimer.claim(worker_id="product-cancel-race", limit=1))[0]
        assert claim.run_id in {accepted.baseline_run_id, accepted.candidate_run_id}
        target_result = TargetResult(
            "private answer", ({"source_id": "gold"},), (), {"cost_usd": 0.01}, None, 10
        )
        evaluator = build_evaluator(claim.evaluator_type, claim.evaluator_config)
        evaluation = evaluator.evaluate(
            EvaluationCase.from_payload(claim.case_payload),
            target_result,
            attempt_number=claim.attempt_number,
        )
        async with asyncio.timeout(15):
            await asyncio.gather(
                sdk.cancel(accepted.id),
                SQLAlchemyResultCommitter(factory).commit_success(
                    claim=claim,
                    lease_version=claim.version,
                    target_result=target_result,
                    evaluation_result=evaluation,
                ),
            )
        # Existing Run semantics permit an already-running success during cooperative cancellation.
        # The other three queued jobs are cancelled; this is not a complete successful experiment.
        assert (await sdk.get(accepted.id)).state == "CANCELLED"
        assert await claimer.claim(worker_id="cancelled-product-drained", limit=1) == ()
        report = await sdk.export(accepted.id, include_private=True)
        verified = verify_durable_report(report, raw_dataset=raw, experiment_id=accepted.id)
        assert verified.verification_scope == "PRIVATE_RECOMPUTED"
        assert verified.quality_status == "EXECUTION_FAILED"
        jobs = [
            job
            for arm in json.loads(report)["result_snapshot"]["arms"].values()
            for job in arm["jobs"]
        ]
        assert len(jobs) == 4
        assert sum(job["job_status"] == "succeeded" for job in jobs) == 1
        assert sum(job["job_status"] == "cancelled" for job in jobs) == 3
        assert sum(job["result_id"] is not None for job in jobs) == 1
