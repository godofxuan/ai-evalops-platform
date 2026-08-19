import json
from datetime import UTC, datetime
from uuid import UUID

from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import get_principal
from app.auth.principals import Principal
from app.domain.enums import ReviewTaskStatus
from app.main import create_app
from app.reviews.schemas import ReviewPacket, ReviewTaskRead
from app.reviews.service import ReviewTaskCreationPermissionError, SQLAlchemyReviewService

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
TASK_ID = UUID("00000000-0000-0000-0000-000000000b01")
REVIEWER = Principal(
    tenant_id=TENANT_ID,
    api_key_id=UUID("00000000-0000-0000-0000-000000000111"),
    key_prefix="evk_111122334455",
    can_review=True,
)
CREATOR = Principal(
    tenant_id=TENANT_ID,
    api_key_id=UUID("00000000-0000-0000-0000-000000000112"),
    key_prefix="evk_222222222222",
    can_create_review_tasks=True,
)


class RecordingReviewService:
    def __init__(self) -> None:
        self.called_with: tuple[Principal, UUID] | None = None

    async def list_tasks(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> list[ReviewTaskRead]:
        self.called_with = (principal, run_id)
        return [
            ReviewTaskRead(
                id=TASK_ID,
                run_id=run_id,
                case_id="case-1",
                status=ReviewTaskStatus.OPEN,
                packet=ReviewPacket(
                    case_id="case-1",
                    question="What is 2+2?",
                    reference_answer="4",
                    candidate_answer="four",
                    citations=[],
                    sources=[],
                ),
                own_submission=None,
                created_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
            )
        ]


class DenyingTaskCreationReviewService:
    async def create_tasks(self, **_kwargs: object) -> list[ReviewTaskRead]:
        raise ReviewTaskCreationPermissionError


class RecordingTaskCreationReviewService:
    def __init__(self) -> None:
        self.source: str | None = None

    async def create_tasks(self, **kwargs: object) -> list[ReviewTaskRead]:
        self.source = str(kwargs["source"])
        return []


async def test_reviewer_task_packet_is_tenant_scoped_and_blinded() -> None:
    service = RecordingReviewService()
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: REVIEWER
    application.state.review_service = service

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/review-tasks",
            params={"run_id": str(RUN_ID)},
        )

    assert response.status_code == 200
    body = response.json()
    encoded = json.dumps(body)
    assert body[0]["packet"]["candidate_answer"] == "four"
    assert body[0]["own_submission"] is None
    assert "metrics" not in encoded
    assert "machine_score" not in encoded
    assert "reviewer_id" not in encoded
    assert "other_submission" not in encoded
    assert service.called_with == (REVIEWER, RUN_ID)


async def test_review_task_creation_permission_has_distinct_403_error() -> None:
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: REVIEWER
    application.state.review_service = DenyingTaskCreationReviewService()

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/v1/runs/{RUN_ID}/review-tasks",
            json={"sample_size": 20},
        )

    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "review_task_creator_required",
            "message": "This credential cannot create human review tasks.",
        }
    }


async def test_request_data_cannot_self_grant_review_task_creation_permission() -> None:
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: REVIEWER
    application.state.review_service = SQLAlchemyReviewService(None)  # type: ignore[arg-type]

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/v1/runs/{RUN_ID}/review-tasks",
            params={"can_create_review_tasks": "true"},
            headers={"X-Can-Create-Review-Tasks": "true"},
            json={"sample_size": 20, "can_create_review_tasks": True},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "review_task_creator_required"


async def test_review_tasks_can_explicitly_use_blinded_agent_artifacts() -> None:
    service = RecordingTaskCreationReviewService()
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: CREATOR
    application.state.review_service = service

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/runs/{RUN_ID}/review-tasks",
            json={"sample_size": 8, "source": "agent_artifact"},
        )

    assert response.status_code == 201
    assert service.source == "agent_artifact"
