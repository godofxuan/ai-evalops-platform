from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from app.agent_eval.mcp_service_adapter import EvalOpsMcpServiceAdapter
from app.auth.principals import Principal
from app.domain.enums import RunStatus
from app.runs.schemas import RunRead

PRINCIPAL = Principal(
    tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
    api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
    key_prefix="evk_001122334455",
)
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")


class RecordingRunService:
    async def get_run(self, *, principal: Principal, run_id: UUID) -> RunRead:
        assert principal == PRINCIPAL
        assert run_id == RUN_ID
        return RunRead(
            id=run_id,
            dataset_version_id=UUID("00000000-0000-0000-0000-000000000501"),
            status=RunStatus.RUNNING,
            total_jobs=8,
            succeeded_jobs=3,
            failed_jobs=0,
            cancelled_jobs=0,
            created_at=datetime(2026, 8, 19, tzinfo=UTC),
            started_at=datetime(2026, 8, 19, tzinfo=UTC),
            finished_at=None,
        )


async def test_mcp_service_adapter_maps_run_status_to_existing_service() -> None:
    unused = cast(Any, object())
    adapter = EvalOpsMcpServiceAdapter(
        run_service=RecordingRunService(),
        result_service=unused,
        agent_artifact_service=unused,
        agent_regression_service=unused,
    )

    result = await adapter.invoke(
        tool_name="get_run_status",
        principal=PRINCIPAL,
        arguments={"run_id": str(RUN_ID)},
    )

    assert result["id"] == str(RUN_ID)
    assert result["status"] == "running"
