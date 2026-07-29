from datetime import UTC, datetime
from uuid import UUID

from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import get_principal
from app.auth.principals import Principal
from app.domain.enums import JobStatus
from app.main import create_app
from app.results.schemas import (
    ArtifactRead,
    CasePage,
    CaseQuery,
    CaseRead,
    ChangedCaseRead,
    DistributionRead,
    MetricsRead,
    RunComparisonRead,
)

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
JOB_ID = UUID("00000000-0000-0000-0000-000000000701")
PRINCIPAL = Principal(
    tenant_id=TENANT_ID,
    api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
    key_prefix="evk_001122334455",
)


class RecordingResultService:
    def __init__(self) -> None:
        self.called_with: tuple[Principal, UUID, CaseQuery] | None = None

    async def list_cases(
        self,
        *,
        principal: Principal,
        run_id: UUID,
        query: CaseQuery,
    ) -> CasePage:
        self.called_with = (principal, run_id, query)
        return CasePage(
            items=[
                CaseRead(
                    job_id=JOB_ID,
                    case_id="case-1",
                    status=JobStatus.FAILED,
                    attempt_count=3,
                    error_code="target_timeout",
                    answer=None,
                    evidence={},
                    metrics={},
                    latency_ms=None,
                    finished_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
                )
            ],
            next_cursor="opaque-next",
        )

    async def get_metrics(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> MetricsRead:
        self.metrics_called_with = (principal, run_id)
        return MetricsRead(
            total_jobs=4,
            completion_rate=1.0,
            success_rate=0.75,
            failure_rate=0.25,
            cancellation_rate=0.0,
            latency=DistributionRead(count=3, mean=20, p50=20, p95=29),
            evaluator_metrics={},
        )

    async def compare_runs(
        self,
        *,
        principal: Principal,
        left_run_id: UUID,
        right_run_id: UUID,
    ) -> RunComparisonRead:
        self.compare_called_with = (principal, left_run_id, right_run_id)
        metrics = await self.get_metrics(principal=principal, run_id=left_run_id)
        return RunComparisonRead(
            warning="dataset_versions_differ",
            intersection_count=2,
            left_only_count=1,
            right_only_count=1,
            left=metrics,
            right=metrics,
            metric_deltas={"score": 0.2},
            only_left_failed=["case-a"],
            only_right_failed=[],
            changed_cases=[
                ChangedCaseRead(
                    case_id="case-b",
                    metric_deltas={"score": 0.2},
                    latency_delta_ms=-10,
                )
            ],
        )

    async def generate_artifacts(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> list[ArtifactRead]:
        self.artifacts_called_with = (principal, run_id)
        return [
            ArtifactRead(
                id=UUID("00000000-0000-0000-0000-000000000a01"),
                run_id=run_id,
                artifact_type="summary_report",
                sha256="a" * 64,
                media_type="application/json",
                byte_size=123,
                created_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
            )
        ]


async def test_case_results_api_passes_filters_and_metric_sort_to_tenant_service() -> None:
    service = RecordingResultService()
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: PRINCIPAL
    application.state.result_service = service

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.get(
            f"/api/v1/runs/{RUN_ID}/cases",
            params={
                "limit": 20,
                "status": "failed",
                "error_code": "target_timeout",
                "sort": "metric",
                "metric_name": "lexical_f1",
                "direction": "desc",
            },
        )

    assert response.status_code == 200
    assert response.json()["next_cursor"] == "opaque-next"
    assert response.json()["items"][0]["error_code"] == "target_timeout"
    assert service.called_with is not None
    principal, run_id, query = service.called_with
    assert principal == PRINCIPAL
    assert run_id == RUN_ID
    assert query.status is JobStatus.FAILED
    assert query.metric_name == "lexical_f1"
    assert query.direction == "desc"


async def test_run_metrics_api_returns_tenant_scoped_aggregate() -> None:
    service = RecordingResultService()
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: PRINCIPAL
    application.state.result_service = service

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/v1/runs/{RUN_ID}/metrics")

    assert response.status_code == 200
    assert response.json()["success_rate"] == 0.75
    assert response.json()["latency"]["p95"] == 29
    assert service.metrics_called_with == (PRINCIPAL, RUN_ID)


async def test_compare_api_returns_dataset_warning_and_intersection_diff() -> None:
    right_run_id = UUID("00000000-0000-0000-0000-000000000602")
    service = RecordingResultService()
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: PRINCIPAL
    application.state.result_service = service

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/runs/compare",
            params={"left_run_id": str(RUN_ID), "right_run_id": str(right_run_id)},
        )

    assert response.status_code == 200
    assert response.json()["warning"] == "dataset_versions_differ"
    assert response.json()["intersection_count"] == 2
    assert response.json()["changed_cases"][0]["case_id"] == "case-b"
    assert service.compare_called_with == (PRINCIPAL, RUN_ID, right_run_id)


async def test_generate_run_artifacts_returns_server_owned_metadata() -> None:
    service = RecordingResultService()
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: PRINCIPAL
    application.state.result_service = service

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post(f"/api/v1/runs/{RUN_ID}/artifacts")

    assert response.status_code == 201
    assert response.json()[0]["artifact_type"] == "summary_report"
    assert "storage_path" not in response.json()[0]
    assert service.artifacts_called_with == (PRINCIPAL, RUN_ID)
