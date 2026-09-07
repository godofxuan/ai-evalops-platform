from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.mark.asyncio
@pytest.mark.parametrize("method,suffix", [("GET", ""), ("POST", "/cancel")])
async def test_product_experiment_controls_require_authentication(method: str, suffix: str) -> None:
    application = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.request(method, f"/api/v1/experiments/{uuid4()}{suffix}")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"
