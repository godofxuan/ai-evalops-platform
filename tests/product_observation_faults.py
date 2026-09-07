"""Real HTTP/worker/PostgreSQL/report regressions for invalid synthetic observations."""

import base64
import json
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

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
from app.product_experiments.client import ProductAPIClient
from app.product_experiments.durable_verification import verify_durable_report
from app.runs.idempotency import canonical_request_hash
from app.targets.http_rag import HTTPRAGTarget
from app.workers.lease_runner import LeaseHeartbeatRunner
from app.workers.worker import EvaluationWorker
from tests.product_http_support import (
    FixtureResolver,
    LoopbackTargetService,
    LoopbackTargetTransport,
)


async def exercise_product_observation_faults(
    application: FastAPI, api: httpx.AsyncClient, headers: dict[str, str], payload: dict[str, Any]
) -> None:
    task = payload["request"]["task_type"]
    factory = cast(AsyncSessionFactory, application.state.session_factory)
    for fault in ["answer", "terminal"] if task == "AGENT_TOOL_USE" else ["answer"]:
        submitted = await api.post(
            "/api/v1/experiments",
            json=payload,
            headers={**headers, "Idempotency-Key": f"observation-fault-{task}-{fault}"},
        )
        assert submitted.status_code == 202
        experiment_id = UUID(submitted.json()["id"])

        def response_for(index: int, fault: str = fault) -> dict[str, Any]:
            response: dict[str, Any] = {
                "answer": "private answer",
                "citations": [{"source_id": "gold"}],
                "trace": {
                    "cost_usd": 0.01,
                    "tool_calls": [],
                    "tool_error": False,
                    "terminal_state": "completed",
                    "source_terminal_state": "answer",
                    "budget_exhausted": False,
                },
            }
            if index == 1:
                if fault == "answer":
                    response["answer"] = "x" * 100001
                else:
                    response["trace"]["terminal_state"] = "failed"
            return response

        async with (
            LoopbackTargetService(response_for=response_for) as service,
            httpx.AsyncClient(transport=LoopbackTargetTransport(service.port)) as client,
        ):

            def target_factory(kind: str, config: Mapping[str, Any]) -> HTTPRAGTarget:
                assert kind == "http_rag"
                return HTTPRAGTarget(config, client=client, resolver=FixtureResolver())

            worker = EvaluationWorker(
                claimer=SQLAlchemyJobClaimer(
                    factory, lease_policy=LeasePolicy(timedelta(seconds=60))
                ),
                result_committer=SQLAlchemyResultCommitter(factory),
                failure_committer=SQLAlchemyFailureCommitter(factory, retry_policy=RetryPolicy()),
                lease_runner=LeaseHeartbeatRunner(
                    heartbeat_service=SQLAlchemyHeartbeatService(
                        factory, lease_duration=timedelta(seconds=60)
                    ),
                    heartbeat_interval_seconds=5,
                ),
                target_factory=target_factory,
            )
            for _ in range(4):
                assert await worker.process_one(worker_id=f"observation-fault-{fault}")
            assert not await worker.process_one(worker_id=f"observation-fault-{fault}")
            assert len(service.requests) == 4
            assert all(request["attempt"] == "1" for request in service.requests)
            assert all(request["body"] == {"question": "q"} for request in service.requests)
            failed_job = service.requests[0]["job_id"]

        # The real target is now closed: report production cannot recall it.
        async with ProductAPIClient(
            "https://evalops.example", headers["Authorization"].removeprefix("Bearer "), http=api
        ) as sdk:
            assert (await sdk.get(experiment_id)).state == "EXECUTION_FAILED"
            report_bytes = await sdk.export(experiment_id, include_private=True)
            assert await sdk.export(experiment_id, include_private=True) == report_bytes
            public_bytes = await sdk.export(experiment_id)
        report = json.loads(report_bytes)
        assert report["result"]["status"] == "EXECUTION_FAILED"
        assert report["result"]["case_count"] == 2
        assert len(report["result"]["execution_errors"]) == 1
        expected_error = (
            "target_answer_too_long" if fault == "answer" else "target_agent_terminal_invalid"
        )
        assert report["result"]["execution_errors"][0]["error_code"] == expected_error
        jobs = [row for arm in report["result_snapshot"]["arms"].values() for row in arm["jobs"]]
        assert len(jobs) == 4
        failed = next(row for row in jobs if row["job_id"] == failed_job)
        assert failed["job_status"] == "failed" and failed["attempt_count"] == 1
        assert failed["accepted_attempt_id"] is None and failed["metrics"] is None
        assert sum(row["accepted_attempt_id"] is not None for row in jobs) == 3
        assert b"x" * 1000 not in report_bytes and b"private answer" not in public_bytes
        verified = verify_durable_report(
            report_bytes, raw_dataset=base64.b64decode(payload["dataset_base64"], validate=True)
        )
        assert verified.verification_scope == "PRIVATE_RECOMPUTED"
        assert verified.quality_status == "EXECUTION_FAILED"
        report["result"]["status"] = "DEMO_PASS"
        report.pop("content_sha256")
        report["content_sha256"] = canonical_request_hash(report)
        with pytest.raises(ValueError, match="recomputation"):
            verify_durable_report(
                json.dumps(report).encode(),
                raw_dataset=base64.b64decode(payload["dataset_base64"], validate=True),
            )
        print(
            f"SYNTHETIC_OBSERVATION_FAULT_VERIFIED task={task} fault={fault} "
            "jobs=4 failed=1 accepted=3 attempts_each=1 private_recomputed=true"
        )
