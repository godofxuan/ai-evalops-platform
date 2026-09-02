from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest

from app.jobs.claiming import ClaimedJob, SQLAlchemyJobClaimer


class _FlowClaimer(SQLAlchemyJobClaimer):
    def __init__(
        self,
        *,
        active_results: list[tuple[ClaimedJob, ...]],
        ensure_result: bool = True,
    ) -> None:
        self.active_results = active_results
        self.ensure_result = ensure_result
        self.events: list[str] = []

    async def _claim_active_scheduler_permit(
        self,
        *,
        worker_id: str,
        eligible_at: datetime,
        skip_locked: bool,
    ) -> tuple[ClaimedJob, ...]:
        self.events.append(f"claim:{'skip' if skip_locked else 'wait'}")
        return self.active_results.pop(0)

    async def _ensure_active_scheduler_round(self, *, eligible_at: datetime) -> bool:
        self.events.append("ensure-round")
        return self.ensure_result


def _claims() -> tuple[ClaimedJob, ...]:
    return cast(tuple[ClaimedJob, ...], (object(),))


@pytest.mark.asyncio
async def test_nonblocking_common_path_claims_existing_permit_without_round_query() -> None:
    claimer = _FlowClaimer(active_results=[_claims()])

    claims = await claimer._claim_once(
        worker_id="worker-1",
        limit=1,
        eligible_at=datetime.now(UTC),
    )

    assert claims
    assert claimer.events == ["claim:skip"]


@pytest.mark.asyncio
async def test_nonblocking_path_creates_round_only_after_no_permit() -> None:
    claimer = _FlowClaimer(active_results=[(), _claims()])

    claims = await claimer._claim_once(
        worker_id="worker-1",
        limit=1,
        eligible_at=datetime.now(UTC),
    )

    assert claims
    assert claimer.events == ["claim:skip", "ensure-round", "claim:skip"]


@pytest.mark.asyncio
async def test_waiting_common_path_blocks_on_existing_permit_without_round_query() -> None:
    claimer = _FlowClaimer(active_results=[_claims()])

    claims = await claimer._claim_once_waiting_for_turn(
        worker_id="worker-1",
        limit=1,
        eligible_at=datetime.now(UTC),
    )

    assert claims
    assert claimer.events == ["claim:wait"]
