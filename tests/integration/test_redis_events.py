import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.events.models import EventType, ProgressEvent
from app.events.publisher import RedisEventPublisher
from app.events.subscriber import RedisEventSubscriber


@pytest.mark.integration
async def test_real_redis_pubsub_is_tenant_and_run_scoped() -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with real Redis")
    redis_url = os.getenv("EVALOPS_REDIS_URL")
    if redis_url is None:
        pytest.skip("EVALOPS_REDIS_URL must point to real Redis")

    client = Redis.from_url(redis_url, decode_responses=True)
    tenant_id = uuid4()
    run_id = uuid4()
    other_run_id = uuid4()
    subscriber = RedisEventSubscriber(client, poll_timeout_seconds=0.1)
    stream = subscriber.listen(tenant_id=tenant_id, run_id=run_id)
    try:
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0.05)
        publisher = RedisEventPublisher(client)
        await publisher.publish(
            ProgressEvent(
                event_type=EventType.JOB_PROGRESS,
                run_id=other_run_id,
                tenant_id=tenant_id,
                timestamp=datetime.now(UTC),
                payload={"status": "wrong-run"},
            )
        )
        await publisher.publish(
            ProgressEvent(
                event_type=EventType.JOB_PROGRESS,
                run_id=run_id,
                tenant_id=tenant_id,
                timestamp=datetime.now(UTC),
                payload={"status": "right-run"},
            )
        )
        event = await asyncio.wait_for(pending, timeout=2)
        while event is None:
            event = await asyncio.wait_for(anext(stream), timeout=2)
        assert event.run_id == run_id
        assert event.payload["status"] == "right-run"
    finally:
        await stream.aclose()
        await client.aclose()
