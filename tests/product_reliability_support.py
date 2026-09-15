"""Real durable repeat panels: PostgreSQL/worker/loopback/report/offline verifier.

Public DNS and peer identity remain injected fixtures, not production TLS proof.
"""

import asyncio
import base64
import json
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.jobs.claiming import SQLAlchemyJobClaimer
from app.jobs.failures import SQLAlchemyFailureCommitter
from app.jobs.heartbeat import SQLAlchemyHeartbeatService
from app.jobs.lease import LeasePolicy
from app.jobs.results import SQLAlchemyResultCommitter
from app.jobs.retry_policy import RetryPolicy
from app.persistence.database import AsyncSessionFactory
from app.product_experiments.client import ProductAPIClient, ProductAPIError
from app.product_experiments.export_service import encode_report
from app.product_experiments.reliability import (
    ReliabilityPlan,
    build_reliability_report,
    verify_reliability_report,
)
from app.product_experiments.reliability_client import (
    collect_reliability_ledger,
    create_reliability_ledger,
    report_reliability_ledger,
    submit_reliability_ledger,
    verify_reliability_ledger,
)
from app.product_experiments.service import ExperimentSubmissionAccepted
from app.product_experiments.submission import DurableExperimentRequest
from app.runs.idempotency import canonical_request_hash
from app.targets.http_rag import HTTPRAGTarget
from app.workers.lease_runner import LeaseHeartbeatRunner
from app.workers.worker import EvaluationWorker
from tests.product_http_support import (
    FixtureResolver,
    LoopbackTargetService,
    LoopbackTargetTransport,
)
from tests.product_learning_support import exercise_learning_bundle


async def exercise_reliability_panels(
    application: FastAPI,
    api: httpx.AsyncClient,
    headers: dict[str, str],
    other_headers: dict[str, str],
    payload: dict[str, Any],
) -> None:
    raw = base64.b64decode(payload["dataset_base64"], validate=True)
    request = DurableExperimentRequest.model_validate_json(json.dumps(payload["request"]))
    factory = cast(AsyncSessionFactory, application.state.session_factory)
    key = headers["Authorization"].removeprefix("Bearer ")
    # Tenant identity from a real authenticated run, not a test-only guessed UUID.
    async with ProductAPIClient("https://evalops.example", key, http=api) as sdk:
        anchor = await sdk.submit(
            request=request,
            dataset_payload=raw,
            idempotency_key=f"reliability-anchor-{request.task_type}",
        )
        await sdk.cancel(anchor.id)
        anchor_report = json.loads(await sdk.export(anchor.id, include_private=True))
        tenant = UUID(anchor_report["result_snapshot"]["tenant_id"])
        for scenario in ("complete", "incomplete"):
            plan = ReliabilityPlan(
                panel_id=uuid4(),
                tenant_id=tenant,
                trial_count=2,
                request=request,
                evalops_sha=application.state.settings.product_execution_code_sha,
                environment_sha256="1" * 64,
                sampling_kind="SYNTHETIC",
            )
            ledger = (
                application.state.settings.artifact_root
                / f"reliability-{request.task_type}-{scenario}"
            )
            create_reliability_ledger(ledger, plan, raw)
            first_submit = await submit_reliability_ledger(ledger, sdk)
            assert await submit_reliability_ledger(ledger, sdk) == first_submit
            submitted = [
                ExperimentSubmissionAccepted.model_validate_json(
                    json.dumps(
                        json.loads((ledger / f"receipt-{trial:02d}" / "receipt.json").read_bytes())[
                            "accepted"
                        ]
                    )
                )
                for trial in (1, 2)
            ]
            assert submitted[0].id != submitted[1].id
            assert (await collect_reliability_ledger(ledger, sdk))["collected_trials"] == 0
            if scenario == "incomplete":
                await sdk.cancel(submitted[1].id)

            def response_for(index: int, scenario: str = scenario) -> dict[str, Any]:
                return {
                    "answer": "x" * 100001
                    if scenario == "incomplete" and index == 1
                    else "private answer",
                    "citations": [{"source_id": "gold"}],
                    "trace": {
                        "cost_usd": 0.01,
                        "tool_calls": [],
                        "tool_error": False,
                        "terminal_state": "completed",
                        "budget_exhausted": False,
                    },
                }

            class RetryOnceTransport(LoopbackTargetTransport):
                fired = False

                def __init__(self, port: int, retry: bool) -> None:
                    super().__init__(port)
                    self.retry = retry

                async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                    if self.retry and not self.fired:
                        self.fired = True
                        raise httpx.ConnectError("synthetic connect failure", request=request)
                    return await super().handle_async_request(request)

            async with (
                LoopbackTargetService(response_for=response_for) as server,
                httpx.AsyncClient(
                    transport=RetryOnceTransport(server.port, scenario == "complete")
                ) as target_client,
            ):

                def target_factory(kind: str, config: Mapping[str, Any]) -> HTTPRAGTarget:
                    assert kind == "http_rag"
                    return HTTPRAGTarget(config, client=target_client, resolver=FixtureResolver())

                worker = EvaluationWorker(
                    claimer=SQLAlchemyJobClaimer(
                        factory, lease_policy=LeasePolicy(timedelta(seconds=60))
                    ),
                    result_committer=SQLAlchemyResultCommitter(factory),
                    failure_committer=SQLAlchemyFailureCommitter(
                        factory,
                        retry_policy=RetryPolicy(
                            base_delay_seconds=0.001, max_delay_seconds=0.001, jitter_ratio=0
                        ),
                    ),
                    lease_runner=LeaseHeartbeatRunner(
                        heartbeat_service=SQLAlchemyHeartbeatService(
                            factory, lease_duration=timedelta(seconds=60)
                        ),
                        heartbeat_interval_seconds=5,
                    ),
                    target_factory=target_factory,
                )
                for _ in range(9 if scenario == "complete" else 4):
                    assert await worker.process_one(worker_id="reliability-worker")
                    await asyncio.sleep(0.01)
                assert not await worker.process_one(worker_id="reliability-worker")
                assert len(server.requests) == (8 if scenario == "complete" else 4)
                assert all(row["body"] == {"question": "q"} for row in server.requests)

            # Target closed: both normal report generation and repeat report recompute offline.
            assert (await collect_reliability_ledger(ledger, sdk))["collected_trials"] == 2
            assert (await collect_reliability_ledger(ledger, sdk))["collected_trials"] == 2
            reports = [
                (trial, (ledger / f"trial-{trial:02d}" / "report.json").read_bytes())
                for trial in (1, 2)
            ]
            for trial in (1, 2):
                exercise_learning_bundle(
                    ledger / f"trial-{trial:02d}",
                    task=request.task_type,
                    scenario=scenario,
                    trial=trial,
                )
            output = ledger.parent / f"{ledger.name}-report"
            report_reliability_ledger(ledger, output)
            assert (
                verify_reliability_ledger(ledger, output)["verification_scope"]
                == "PRIVATE_RECOMPUTED_PANEL"
            )
            report = build_reliability_report(plan=plan, raw_dataset=raw, reports=reports)
            encoded = encode_report(report)
            verify_reliability_report(encoded, plan=plan, raw_dataset=raw, reports=reports[::-1])
            assert b"private answer" not in encoded and b"x" * 1000 not in encoded
            assert report["formal_quality_claim_allowed"] is False
            summaries = [report["arms"][label]["summary"] for label in ("baseline", "candidate")]
            if scenario == "complete":
                assert report["status"] == "COMPLETE_DESCRIPTIVE_PANEL"
                assert all(row["empirical_all_at_k"] == 1 for row in summaries)
                assert sum(row["known_attempts"] for row in summaries) == 9
                assert sum(row["known_retries"] for row in summaries) == 1
            else:
                assert report["status"] == "INSUFFICIENT_EVIDENCE"
                assert all(row["empirical_all_at_k"] is None for row in summaries)
                assert sum(row["counts"]["CANCELLED"] for row in summaries) == 4
                assert sum(row["counts"]["EXECUTION_FAILED"] for row in summaries) == 1
            missing = build_reliability_report(plan=plan, raw_dataset=raw, reports=reports[:1])
            assert missing["status"] == "INSUFFICIENT_EVIDENCE"
            assert all(
                missing["arms"][label]["summary"]["counts"]["MISSING_TRIAL"] == 2
                for label in ("baseline", "candidate")
            )
            report["status"] = "FORGED_PASS"
            report.pop("content_sha256")
            report["content_sha256"] = canonical_request_hash(report)
            with pytest.raises(ValueError, match="recomputation"):
                verify_reliability_report(
                    encode_report(report), plan=plan, raw_dataset=raw, reports=reports
                )
            async with ProductAPIClient(
                "https://evalops.example",
                other_headers["Authorization"].removeprefix("Bearer "),
                http=api,
            ) as outsider:
                with pytest.raises(ProductAPIError, match="api_http_404"):
                    await outsider.export(submitted[0].id, include_private=True)
            print(
                f"SYNTHETIC_RELIABILITY_PANEL_VERIFIED task={request.task_type} "
                f"scenario={scenario} trials=2 private_recomputed=true"
            )
