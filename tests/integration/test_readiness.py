import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core.config import Settings
from app.health.service import build_infrastructure_readiness_probe
from app.main import create_app
from app.persistence.database import create_database_engine
from app.persistence.redis import create_redis_client

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
async def test_readiness_uses_real_postgresql_redis_artifacts_and_migration(
    tmp_path: Path,
) -> None:
    if os.getenv("EVALOPS_RUN_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_INTEGRATION=1 with real PostgreSQL and Redis")

    database_url = os.getenv("EVALOPS_DATABASE_URL")
    redis_url = os.getenv("EVALOPS_REDIS_URL")
    if database_url is None or redis_url is None:
        pytest.fail("integration test requires EVALOPS_DATABASE_URL and EVALOPS_REDIS_URL")

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(database_url),
        redis_url=SecretStr(redis_url),
        artifact_root=tmp_path,
        alembic_config_path=PROJECT_ROOT / "alembic.ini",
    )
    engine = create_database_engine(settings)
    redis_client = create_redis_client(settings)
    probe = build_infrastructure_readiness_probe(
        settings=settings,
        engine=engine,
        redis_client=redis_client,
    )
    transport = ASGITransport(app=create_app(settings=settings, readiness_probe=probe))

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health/ready")
    finally:
        await redis_client.aclose()
        await engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {
        "postgresql": {"status": "ok", "error_code": None},
        "redis": {"status": "ok", "error_code": None},
        "artifacts": {"status": "ok", "error_code": None},
        "migrations": {"status": "ok", "error_code": None},
    }
