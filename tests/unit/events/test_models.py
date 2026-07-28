import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.events.models import EventType, ProgressEvent, run_event_channel

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
EVENT_ID = UUID("00000000-0000-0000-0000-000000000901")


def test_progress_event_round_trips_and_channel_is_tenant_scoped() -> None:
    event = ProgressEvent(
        event_id=EVENT_ID,
        event_type=EventType.JOB_PROGRESS,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        timestamp=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
        payload={"job_id": "job-1", "completed": 3},
    )

    encoded = event.model_dump_json()
    decoded = ProgressEvent.model_validate_json(encoded)

    assert decoded == event
    assert json.loads(encoded)["event_type"] == "job_progress"
    assert run_event_channel(tenant_id=TENANT_ID, run_id=RUN_ID) == (
        f"evalops:{TENANT_ID}:run:{RUN_ID}"
    )


def test_progress_event_rejects_unknown_event_type() -> None:
    with pytest.raises(ValidationError):
        ProgressEvent(
            event_id=EVENT_ID,
            event_type="made_up",
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            timestamp=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
            payload={},
        )
