import asyncio
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any

from pydantic import SecretStr

from app.core.config import Settings
from app.domain.evaluation import EvaluationResult, TargetResult, TokenUsage
from app.jobs.claiming import SQLAlchemyJobClaimer
from app.jobs.failures import SQLAlchemyFailureCommitter
from app.jobs.heartbeat import LeaseLostError
from app.jobs.lease import LeasePolicy
from app.jobs.reaper import SQLAlchemyJobReaper
from app.jobs.results import SQLAlchemyResultCommitter
from app.jobs.retry_policy import RetryPolicy
from app.persistence.database import create_database_engine, create_session_factory
from scripts.experiment_support import ExperimentClient, ExperimentError
from scripts.fault_matrix_evidence import reconcile_fault_run
from scripts.gate1_database import collect_reconciliation_bundle


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self._value = value

    def now(self) -> datetime:
        return self._value


class FixedRandom:
    def random(self) -> float:
        return 0.5


SCENARIO_NAMES = {
    "B": "lease_expires_during_execution",
    "C": "reclaim_then_worker_a_late_result",
    "D": "reclaim_then_worker_a_late_failure",
    "H": "dual_reaper_competition",
}


async def run_database_lease_scenario(
    *,
    client: ExperimentClient,
    database_url: str,
    scenario_id: str,
    repetition: int,
    source_commit: str,
) -> dict[str, Any]:
    if scenario_id not in SCENARIO_NAMES:
        raise ValueError(f"unsupported database lease scenario: {scenario_id}")
    case_count = 20 if scenario_id == "H" else 1
    cases = [
        {
            "case_id": f"fault-{scenario_id.lower()}-{repetition}-{index:02d}",
            "question": "deterministic lease fault",
            "expected_answer": "mock answer",
            "metadata": {},
        }
        for index in range(case_count)
    ]
    version_id = await client.create_dataset_version(
        name_prefix=f"fault-{scenario_id.lower()}-{repetition}",
        cases=cases,
    )
    run = await client.create_run(
        dataset_version_id=version_id,
        target_config={"answer": "mock answer"},
        evaluator_config={"max_attempts": 3},
        idempotency_key=f"fault-{scenario_id.lower()}-{repetition}-{version_id}",
        component_version="fault-matrix-v1",
        source_commit=source_commit,
    )
    run_id = str(run["id"])

    settings = Settings(_env_file=None, database_url=SecretStr(database_url))
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    lease_seconds = 2
    claimed_at = datetime.now(UTC)
    retry_policy = RetryPolicy(
        base_delay_seconds=1,
        max_delay_seconds=1,
        jitter_ratio=0,
        random_source=FixedRandom(),
    )
    stale_result_attempted = 0
    stale_result_accepted = 0
    stale_failure_attempted = 0
    stale_failure_accepted = 0
    try:
        worker_a = SQLAlchemyJobClaimer(
            session_factory,
            lease_policy=LeasePolicy(timedelta(seconds=lease_seconds)),
            clock=FixedClock(claimed_at),
        )
        claims_a = await worker_a.claim(
            worker_id=f"fault-worker-a-{scenario_id}-{repetition}",
            limit=case_count,
        )
        if len(claims_a) != case_count:
            raise ExperimentError(
                f"scenario {scenario_id} claimed {len(claims_a)} of {case_count} Jobs"
            )

        expired_at = claimed_at + timedelta(seconds=lease_seconds + 1)
        recovery_started = perf_counter()
        if scenario_id == "H":
            reapers = (
                SQLAlchemyJobReaper(
                    session_factory,
                    retry_policy=retry_policy,
                    clock=FixedClock(expired_at),
                    reaper_id=f"fault-reaper-a-{repetition}",
                ),
                SQLAlchemyJobReaper(
                    session_factory,
                    retry_policy=retry_policy,
                    clock=FixedClock(expired_at),
                    reaper_id=f"fault-reaper-b-{repetition}",
                ),
            )
            batches = await asyncio.gather(*(reaper.reap(limit=case_count) for reaper in reapers))
            reaped = tuple(item for batch in batches for item in batch)
        else:
            reaper = SQLAlchemyJobReaper(
                session_factory,
                retry_policy=retry_policy,
                clock=FixedClock(expired_at),
                reaper_id=f"fault-reaper-{scenario_id}-{repetition}",
            )
            reaped = await reaper.reap(limit=case_count)
        if len(reaped) != case_count or len({item.job_id for item in reaped}) != case_count:
            raise ExperimentError(
                f"scenario {scenario_id} did not reap each expired Job exactly once"
            )

        reclaim_at = expired_at + timedelta(seconds=2)
        worker_b = SQLAlchemyJobClaimer(
            session_factory,
            lease_policy=LeasePolicy(timedelta(seconds=lease_seconds)),
            clock=FixedClock(reclaim_at),
        )
        claims_b = await worker_b.claim(
            worker_id=f"fault-worker-b-{scenario_id}-{repetition}",
            limit=case_count,
        )
        if len(claims_b) != case_count:
            raise ExperimentError(
                f"scenario {scenario_id} reclaimed {len(claims_b)} of {case_count} Jobs"
            )
        result_committer = SQLAlchemyResultCommitter(
            session_factory,
            clock=FixedClock(reclaim_at + timedelta(milliseconds=100)),
        )
        target_result = TargetResult(
            answer="mock answer",
            citations=(),
            sources=(),
            trace={},
            token_usage=TokenUsage(input_tokens=1, output_tokens=1),
            latency_ms=25,
        )
        evaluation_result = EvaluationResult(metrics={"exact_match": 1.0})
        for claim in claims_b:
            await result_committer.commit_success(
                claim=claim,
                lease_version=claim.version,
                target_result=target_result,
                evaluation_result=evaluation_result,
            )
        recovery_seconds = perf_counter() - recovery_started

        if scenario_id == "C":
            stale_result_attempted = 1
            try:
                await result_committer.commit_success(
                    claim=claims_a[0],
                    lease_version=claims_a[0].version,
                    target_result=target_result,
                    evaluation_result=evaluation_result,
                )
            except LeaseLostError:
                pass
            else:
                stale_result_accepted = 1
        elif scenario_id == "D":
            stale_failure_attempted = 1
            failure_committer = SQLAlchemyFailureCommitter(
                session_factory,
                retry_policy=retry_policy,
                clock=FixedClock(reclaim_at + timedelta(milliseconds=200)),
            )
            try:
                await failure_committer.commit_failure(
                    claim=claims_a[0],
                    lease_version=claims_a[0].version,
                    error=TimeoutError("deliberately late failure"),
                )
            except LeaseLostError:
                pass
            else:
                stale_failure_accepted = 1
    finally:
        await engine.dispose()

    bundle = await collect_reconciliation_bundle(database_url=database_url, run_id=run_id)
    reconciled = reconcile_fault_run(
        bundle,
        expected_submitted=case_count,
        stale_result_attempted_count=stale_result_attempted,
        stale_result_accepted_count=stale_result_accepted,
        stale_failure_attempted_count=stale_failure_attempted,
        stale_failure_accepted_count=stale_failure_accepted,
    )
    return {
        "scenario_id": scenario_id,
        "scenario": SCENARIO_NAMES[scenario_id],
        "repetition": repetition,
        "recovery_seconds": recovery_seconds,
        "logical_lease_seconds": lease_seconds,
        "logical_recovery_eligibility_seconds": lease_seconds + 2,
        "reaped_count": len(reaped),
        "unique_reaped_count": len({item.job_id for item in reaped}),
        **reconciled,
        "raw_reconciliation": bundle,
    }
