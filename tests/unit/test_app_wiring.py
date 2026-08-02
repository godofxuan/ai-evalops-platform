import asyncio
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


async def test_app_lifespan_wires_outbox_tasks_and_operator_target_registry(
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
    dispatcher_started = asyncio.Event()
    dispatcher_stopped = asyncio.Event()
    cleanup_started = asyncio.Event()
    cleanup_stopped = asyncio.Event()
    dispatcher_arguments: dict[str, object] = {}

    class RecordingDispatcher:
        def __init__(self, **values: object) -> None:
            dispatcher_arguments.update(values)

    class RecordingMaintenance:
        def __init__(
            self,
            _session_factory: object,
            *,
            retention_seconds: float,
        ) -> None:
            assert retention_seconds == 7_200

    async def record_outbox_loop(
        _dispatcher: object,
        *,
        stop_requested: asyncio.Event,
        poll_seconds: float,
        batch_size: int,
        logger: object | None = None,
    ) -> None:
        del logger
        assert poll_seconds == 0.5
        assert batch_size == 50
        dispatcher_started.set()
        await stop_requested.wait()
        dispatcher_stopped.set()

    async def record_cleanup_loop(
        maintenance: object,
        *,
        stop_requested: asyncio.Event,
        interval_seconds: float,
        batch_size: int,
        metrics: object,
        logger: object | None = None,
    ) -> None:
        del logger
        assert isinstance(maintenance, RecordingMaintenance)
        assert interval_seconds == 3
        assert batch_size == 17
        assert metrics is application.state.metrics
        cleanup_started.set()
        await stop_requested.wait()
        cleanup_stopped.set()

    monkeypatch.setattr(
        main_module,
        "OutboxDispatcher",
        RecordingDispatcher,
    )
    monkeypatch.setattr(
        main_module,
        "run_outbox_dispatch_loop",
        record_outbox_loop,
        raising=False,
    )
    monkeypatch.setattr(
        main_module,
        "SQLAlchemyOutboxMaintenance",
        RecordingMaintenance,
        raising=False,
    )
    monkeypatch.setattr(
        main_module,
        "run_outbox_cleanup_loop",
        record_cleanup_loop,
        raising=False,
    )
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
        outbox_retention_seconds=7_200,
        outbox_cleanup_interval_seconds=3,
        outbox_cleanup_batch_size=17,
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
        await asyncio.wait_for(dispatcher_started.wait(), timeout=1)
        await asyncio.wait_for(cleanup_started.wait(), timeout=1)
        assert application.state.outbox_dispatcher_task.done() is False
        assert application.state.outbox_cleanup_task.done() is False
        assert dispatcher_arguments["metrics"] is application.state.metrics
        with pytest.raises(RunDatasetVersionNotFoundError):
            await application.state.run_service.create_run(
                principal=principal,
                idempotency_key="app-registry-wiring",
                request=request,
            )

    assert dispatcher_stopped.is_set()
    assert cleanup_stopped.is_set()
    assert application.state.outbox_dispatcher_task.done() is True
    assert application.state.outbox_cleanup_task.done() is True
