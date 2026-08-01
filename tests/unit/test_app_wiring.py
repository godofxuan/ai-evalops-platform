from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

import app.main as main_module
from app.auth.principals import Principal
from app.core.config import Settings
from app.runs.schemas import RunCreate
from app.runs.service import RunDatasetVersionNotFoundError


class EmptyResult:
    def scalar_one_or_none(self) -> None:
        return None

    def one_or_none(self) -> None:
        return None


class EmptySession:
    async def __aenter__(self) -> "EmptySession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> EmptyResult:
        return EmptyResult()


class EmptySessionFactory:
    def __call__(self) -> EmptySession:
        return EmptySession()


class DisposableEngine:
    async def dispose(self) -> None:
        return None


class ClosableRedis:
    async def aclose(self) -> None:
        return None


async def test_app_lifespan_wires_operator_http_target_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = DisposableEngine()
    redis = ClosableRedis()
    monkeypatch.setattr(main_module, "create_database_engine", lambda _settings: engine)
    monkeypatch.setattr(
        main_module,
        "create_session_factory",
        lambda _engine: EmptySessionFactory(),
    )
    monkeypatch.setattr(main_module, "create_redis_client", lambda _settings: redis)
    monkeypatch.setattr(
        main_module,
        "build_infrastructure_readiness_probe",
        lambda **_kwargs: SimpleNamespace(),
    )
    settings = Settings(
        _env_file=None,
        artifact_root=tmp_path,
        metrics_enabled=False,
        otel_enabled=False,
        http_target_registry={
            "rag-production": {
                "version": "rag-v1",
                "config": {
                    "base_url": "https://rag.example.com",
                    "endpoint": "/v1/query",
                },
            }
        },
    )
    application = main_module.create_app(settings=settings)
    request = RunCreate.model_validate(
        {
            "dataset_version_id": "00000000-0000-0000-0000-000000000401",
            "target": {
                "type": "http_rag",
                "config": {"target_id": "rag-production"},
                "version": "rag-v1",
            },
            "evaluator": {
                "type": "basic_answer",
                "config": {},
                "version": "eval-v1",
            },
        }
    )
    principal = Principal(
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
        api_key_id=UUID("00000000-0000-0000-0000-000000000101"),
        key_prefix="evk_001122334455",
    )

    async with application.router.lifespan_context(application):
        with pytest.raises(RunDatasetVersionNotFoundError):
            await application.state.run_service.create_run(
                principal=principal,
                idempotency_key="app-registry-wiring",
                request=request,
            )
