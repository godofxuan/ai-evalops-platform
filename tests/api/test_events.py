from collections.abc import AsyncIterator
from uuid import UUID

from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import get_principal
from app.auth.principals import Principal
from app.main import create_app

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
PRINCIPAL = Principal(
    tenant_id=TENANT_ID,
    api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
    key_prefix="evk_001122334455",
)


class FiniteEventStream:
    def __init__(self) -> None:
        self.called_with: tuple[Principal, UUID] | None = None

    async def open(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> AsyncIterator[str]:
        self.called_with = (principal, run_id)

        async def generate() -> AsyncIterator[str]:
            yield 'id: 1\nevent: snapshot\ndata: {"status":"running"}\n\n'

        return generate()


async def test_run_events_are_authenticated_tenant_scoped_sse() -> None:
    event_stream = FiniteEventStream()
    application = create_app()
    application.dependency_overrides[get_principal] = lambda: PRINCIPAL
    application.state.run_event_stream = event_stream

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/v1/runs/{RUN_ID}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert "event: snapshot" in response.text
    assert event_stream.called_with == (PRINCIPAL, RUN_ID)
