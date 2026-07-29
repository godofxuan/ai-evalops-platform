import json
from datetime import UTC, datetime
from uuid import UUID

from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import get_principal
from app.auth.principals import Principal
from app.domain.enums import ReviewTaskStatus
from app.main import create_app
from app.reviews.schemas import ReviewPacket, ReviewTaskRead

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
TASK_ID = UUID("00000000-0000-0000-0000-000000000b01")
REVIEWER = Principal(
    tenant_id=TENANT_ID,
    api_key_id=UUID("00000000-0000-0000-0000-000000000111"),
    key_prefix="evk_111122334455",
    can_review=True,
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
