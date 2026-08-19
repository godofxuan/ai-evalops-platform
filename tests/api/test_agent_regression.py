from datetime import UTC, datetime
from uuid import UUID

from httpx import ASGITransport, AsyncClient

from app.agent_eval.schemas import AgentRegressionRequest, AgentRegressionResponse
from app.auth.dependencies import get_principal
from app.auth.principals import Principal
from app.main import create_app

PRINCIPAL = Principal(
    tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
    api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
    key_prefix="evk_001122334455",
)
LEFT_RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
RIGHT_RUN_ID = UUID("00000000-0000-0000-0000-000000000602")


class RecordingRegressionService:
    async def compare(
        self,
        *,
        principal: Principal,
        request: AgentRegressionRequest,
    ) -> AgentRegressionResponse:
        assert principal == PRINCIPAL
        assert request.left_run_id == LEFT_RUN_ID
        return AgentRegressionResponse(
            comparison_id=UUID("00000000-0000-0000-0000-000000000603"),
            left_run_id=LEFT_RUN_ID,
            right_run_id=RIGHT_RUN_ID,
            case_set_policy="exact",
            common_case_ids=[f"case-{index}" for index in range(8)],
            common_case_ids_sha256="a" * 64,
            intersection_count=8,
            left_only_case_ids=[],
            right_only_case_ids=[],
            left_only_count=0,
            right_only_count=0,
            common_case_metrics={
                "task_success_rate": {"left": 0.875, "right": 0.75},
                "latency_p95_ms": {"left": 120.0, "right": 180.0},
                "unauthorized_result_leak_count": {"left": 0, "right": 0},
                "tool_error_rate": {"left": 0.0, "right": 0.0},
                "terminal_distribution": {"answer": {"left": 7, "right": 6}},
                "failure_category_distribution": {},
                "metric_evidence": {},
                "metric_trust": {},
            },
            left_full_run_diagnostics={
                "case_count": 8,
                "case_ids_sha256": "a" * 64,
                "task_success_rate": 0.875,
                "latency_p95_ms": 120.0,
                "terminal_distribution": {"answer": 7},
                "failure_category_distribution": {},
            },
            right_full_run_diagnostics={
                "case_count": 8,
                "case_ids_sha256": "a" * 64,
                "task_success_rate": 0.75,
                "latency_p95_ms": 180.0,
                "terminal_distribution": {"answer": 6},
                "failure_category_distribution": {},
            },
            evidence_manifest=[],
            gate_executed=True,
            evidence_sufficient=True,
            gate_status="failed",
            gate_passed=False,
            gate_violations=["task_success", "latency_p95"],
            warnings=[],
            created_at=datetime(2026, 8, 20, tzinfo=UTC),
        )


async def test_agent_regression_api_returns_report_and_configured_gate_decision() -> None:
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: PRINCIPAL
    application.state.agent_regression_service = RecordingRegressionService()

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/agent-regression/compare",
            json={
                "left_run_id": str(LEFT_RUN_ID),
                "right_run_id": str(RIGHT_RUN_ID),
                "gate": {
                    "task_success_min": 0.8,
                    "latency_p95_max_regression_pct": 20.0,
                    "minimum_metric_sample_count": 2,
                    "case_set_policy": "exact",
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["gate_passed"] is False
    assert response.json()["gate_violations"] == ["task_success", "latency_p95"]
    assert response.json()["common_case_metrics"]["task_success_rate"]["right"] == 0.75
