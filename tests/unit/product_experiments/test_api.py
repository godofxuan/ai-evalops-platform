from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


def test_submission_openapi_documents_the_actual_nested_budget_contract() -> None:
    operation = create_app().openapi()["paths"]["/api/v1/experiments"]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    request = schema["properties"]["request"]
    assert request["properties"]["max_active_jobs"]["maximum"] == 64
    assert request["properties"]["max_observation_bytes"]["maximum"] == 256 * 1024 * 1024
    assert request["properties"]["baseline"]["additionalProperties"] is False


async def test_product_experiment_submission_requires_authentication() -> None:
    application = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/experiments", content=b"not-json")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,suffix", [("GET", ""), ("POST", "/cancel"), ("POST", "/export")])
async def test_product_experiment_controls_require_authentication(method: str, suffix: str) -> None:
    application = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.request(method, f"/api/v1/experiments/{uuid4()}{suffix}")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"
