import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.auth.principals import Principal
from app.core.telemetry import Telemetry
from app.domain.enums import RunStatus
from app.observability.metrics import PlatformMetrics
from app.runs.idempotency import canonical_request_hash
from app.runs.repository import (
    DatasetVersionSource,
    NewRun,
    RunSnapshot,
)
from app.runs.schemas import RunCreate
from app.runs.service import (
    IdempotencyConflictError,
    InvalidEvaluatorConfigurationError,
    InvalidTargetConfigurationError,
    SQLAlchemyRunService,
)

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
API_KEY_ID = UUID("00000000-0000-0000-0000-000000000101")
DATASET_VERSION_ID = UUID("00000000-0000-0000-0000-000000000401")
RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
PRINCIPAL = Principal(
    tenant_id=TENANT_ID,
    api_key_id=API_KEY_ID,
    key_prefix="evk_001122334455",
)


class RecordingRunRepository:
    def __init__(self, artifact_sha256: str) -> None:
        self.artifact_sha256 = artifact_sha256
        self.new_run: NewRun | None = None

    async def find_by_idempotency_key(
        self,
        *,
        tenant_id: UUID,
        idempotency_key: str,
    ) -> RunSnapshot | None:
        assert tenant_id == TENANT_ID
        assert idempotency_key == "create-rag-v1"
        return None

    async def get_dataset_version_source(
        self,
        *,
        tenant_id: UUID,
        dataset_version_id: UUID,
    ) -> DatasetVersionSource | None:
        assert tenant_id == TENANT_ID
        assert dataset_version_id == DATASET_VERSION_ID
        return DatasetVersionSource(
            dataset_version_id=DATASET_VERSION_ID,
            sha256=self.artifact_sha256,
            case_count=2,
        )

    async def create_or_replay(self, new_run: NewRun) -> RunSnapshot:
        self.new_run = new_run
        return RunSnapshot(
            id=RUN_ID,
            dataset_version_id=DATASET_VERSION_ID,
            request_hash=new_run.request_hash,
            status=RunStatus.QUEUED,
            total_jobs=2,
            succeeded_jobs=0,
            failed_jobs=0,
            cancelled_jobs=0,
            created_at=datetime(2026, 7, 29, 13, 0, tzinfo=UTC),
            started_at=None,
            finished_at=None,
            created_now=True,
        )

    async def get_run(self, *, tenant_id: UUID, run_id: UUID) -> RunSnapshot | None:
        raise AssertionError(f"unexpected get_run({tenant_id}, {run_id})")


class ConcurrentWinnerRunRepository(RecordingRunRepository):
    async def create_or_replay(self, new_run: NewRun) -> RunSnapshot:
        self.new_run = new_run
        return RunSnapshot(
            id=RUN_ID,
            dataset_version_id=DATASET_VERSION_ID,
            request_hash="b" * 64,
            status=RunStatus.QUEUED,
            total_jobs=2,
            succeeded_jobs=0,
            failed_jobs=0,
            cancelled_jobs=0,
            created_at=datetime(2026, 7, 29, 13, 0, tzinfo=UTC),
            started_at=None,
            finished_at=None,
        )


class StaticArtifactStore:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.requested_sha256: str | None = None

    async def put_bytes(self, _content: bytes) -> object:
        raise AssertionError("run creation must not write the dataset artifact")

    async def get_bytes(self, sha256: str) -> bytes:
        self.requested_sha256 = sha256
        return self.content


class ReplayRunRepository:
    def __init__(self, snapshot: RunSnapshot) -> None:
        self.snapshot = snapshot

    async def find_by_idempotency_key(
        self,
        *,
        tenant_id: UUID,
        idempotency_key: str,
    ) -> RunSnapshot:
        assert tenant_id == TENANT_ID
        assert idempotency_key == "create-rag-v1"
        return self.snapshot

    async def get_dataset_version_source(self, **_kwargs: object) -> None:
        raise AssertionError("a replay must not load dataset metadata")

    async def create_or_replay(self, _new_run: NewRun) -> RunSnapshot:
        raise AssertionError("a replay must not create Runs or Jobs")

    async def get_run(self, **_kwargs: object) -> None:
        raise AssertionError("unexpected get_run")


class ArtifactStoreThatMustNotRead:
    async def put_bytes(self, _content: bytes) -> object:
        raise AssertionError("unexpected put_bytes")

    async def get_bytes(self, _sha256: str) -> bytes:
        raise AssertionError("a replay must not read artifact bytes")


class NewRequestRepositoryThatMustNotLoadSource:
    async def find_by_idempotency_key(self, **_kwargs: object) -> None:
        return None

    async def get_dataset_version_source(self, **_kwargs: object) -> None:
        raise AssertionError("invalid evaluator config must fail before dataset I/O")

    async def create_or_replay(self, _new_run: NewRun) -> RunSnapshot:
        raise AssertionError("invalid evaluator config must not create a Run")

    async def get_run(self, **_kwargs: object) -> None:
        raise AssertionError("unexpected get_run")


def make_run_request() -> RunCreate:
    return RunCreate.model_validate(
        {
            "dataset_version_id": str(DATASET_VERSION_ID),
            "target": {"type": "mock", "config": {"answer": "fixed"}, "version": "target-v1"},
            "evaluator": {
                "type": "basic_answer",
                "config": {"max_attempts": 3},
                "version": "eval-v1",
            },
            "source_commit": "abc123",
        }
    )


async def test_create_run_snapshots_validated_cases_and_reproducibility_hashes() -> None:
    content = b"\n".join(
        json.dumps(
            {
                "case_id": case_id,
                "question": question,
                "expected_answer": answer,
                "metadata": {},
            },
            separators=(",", ":"),
        ).encode()
        for case_id, question, answer in (
            ("case-1", "q1", "a1"),
            ("case-2", "q2", "a2"),
        )
    )
    artifact_sha256 = hashlib.sha256(content).hexdigest()
    repository = RecordingRunRepository(artifact_sha256)
    artifact_store = StaticArtifactStore(content)
    service = SQLAlchemyRunService(repository=repository, artifact_store=artifact_store)
    request = make_run_request()

    created = await service.create_run(
        principal=PRINCIPAL,
        idempotency_key="create-rag-v1",
        request=request,
    )

    assert created.id == RUN_ID
    assert artifact_store.requested_sha256 == artifact_sha256
    assert repository.new_run is not None
    assert repository.new_run.tenant_id == TENANT_ID
    assert repository.new_run.created_by == API_KEY_ID
    assert repository.new_run.dataset_hash == artifact_sha256
    assert repository.new_run.target_config_hash != repository.new_run.evaluator_config_hash
    assert repository.new_run.max_attempts == 3
    assert tuple(case["case_id"] for case in repository.new_run.cases) == (
        "case-1",
        "case-2",
    )
    assert repository.new_run.origin_traceparent is None


async def test_create_run_snapshots_current_platform_traceparent() -> None:
    content = (
        b'{"case_id":"case-1","question":"q1","expected_answer":"a1","metadata":{}}\n'
        b'{"case_id":"case-2","question":"q2","expected_answer":"a2","metadata":{}}'
    )
    repository = RecordingRunRepository(hashlib.sha256(content).hexdigest())
    telemetry = Telemetry(
        service_name="evalops-api-test",
        span_processors=(SimpleSpanProcessor(InMemorySpanExporter()),),
    )
    service = SQLAlchemyRunService(
        repository=repository,
        artifact_store=StaticArtifactStore(content),
        telemetry=telemetry,
    )

    with telemetry.start_as_current_span("run.create"):
        expected_traceparent = telemetry.capture_traceparent()
        await service.create_run(
            principal=PRINCIPAL,
            idempotency_key="create-rag-v1",
            request=make_run_request(),
        )

    assert expected_traceparent is not None
    assert repository.new_run is not None
    assert repository.new_run.origin_traceparent == expected_traceparent


async def test_create_run_replays_same_request_without_recreating_jobs() -> None:
    request = make_run_request()
    request_hash = canonical_request_hash(request.model_dump(mode="json", exclude_none=False))
    snapshot = RunSnapshot(
        id=RUN_ID,
        dataset_version_id=DATASET_VERSION_ID,
        request_hash=request_hash,
        status=RunStatus.QUEUED,
        total_jobs=2,
        succeeded_jobs=0,
        failed_jobs=0,
        cancelled_jobs=0,
        created_at=datetime(2026, 7, 29, 13, 0, tzinfo=UTC),
        started_at=None,
        finished_at=None,
    )

    class TelemetryThatMustNotCapture:
        def capture_traceparent(self) -> str:
            raise AssertionError("an idempotent replay must preserve the first trace context")

    service = SQLAlchemyRunService(
        repository=ReplayRunRepository(snapshot),
        artifact_store=ArtifactStoreThatMustNotRead(),
        telemetry=TelemetryThatMustNotCapture(),  # type: ignore[arg-type]
    )

    replayed = await service.create_run(
        principal=PRINCIPAL,
        idempotency_key="create-rag-v1",
        request=request,
    )

    assert replayed.id == RUN_ID
    assert replayed.total_jobs == 2


async def test_run_created_metric_excludes_idempotency_replay() -> None:
    content = (
        b'{"case_id":"case-1","question":"q1","expected_answer":"a1","metadata":{}}\n'
        b'{"case_id":"case-2","question":"q2","expected_answer":"a2","metadata":{}}'
    )
    artifact_sha256 = hashlib.sha256(content).hexdigest()
    metrics = PlatformMetrics()
    request = make_run_request()
    creator = SQLAlchemyRunService(
        repository=RecordingRunRepository(artifact_sha256),
        artifact_store=StaticArtifactStore(content),
        metrics=metrics,
    )

    await creator.create_run(
        principal=PRINCIPAL,
        idempotency_key="create-rag-v1",
        request=request,
    )
    request_hash = canonical_request_hash(request.model_dump(mode="json", exclude_none=False))
    replay = SQLAlchemyRunService(
        repository=ReplayRunRepository(
            RunSnapshot(
                id=RUN_ID,
                dataset_version_id=DATASET_VERSION_ID,
                request_hash=request_hash,
                status=RunStatus.QUEUED,
                total_jobs=2,
                succeeded_jobs=0,
                failed_jobs=0,
                cancelled_jobs=0,
                created_at=datetime(2026, 7, 29, 13, 0, tzinfo=UTC),
                started_at=None,
                finished_at=None,
            )
        ),
        artifact_store=ArtifactStoreThatMustNotRead(),
        metrics=metrics,
    )
    await replay.create_run(
        principal=PRINCIPAL,
        idempotency_key="create-rag-v1",
        request=request,
    )

    assert "run_created_total 1.0" in metrics.render().decode("utf-8")


async def test_get_run_returns_persisted_metric_summary() -> None:
    snapshot = RunSnapshot(
        id=RUN_ID,
        dataset_version_id=DATASET_VERSION_ID,
        request_hash="a" * 64,
        status=RunStatus.SUCCEEDED,
        total_jobs=2,
        succeeded_jobs=2,
        failed_jobs=0,
        cancelled_jobs=0,
        created_at=datetime(2026, 7, 29, 13, 0, tzinfo=UTC),
        started_at=datetime(2026, 7, 29, 13, 1, tzinfo=UTC),
        finished_at=datetime(2026, 7, 29, 13, 2, tzinfo=UTC),
        metrics={"success_rate": 1.0, "latency.p95_ms": 42.0},
    )

    class MetricsRunRepository(ReplayRunRepository):
        async def get_run(
            self,
            *,
            tenant_id: UUID,
            run_id: UUID,
        ) -> RunSnapshot:
            assert tenant_id == TENANT_ID
            assert run_id == RUN_ID
            return snapshot

    service = SQLAlchemyRunService(
        repository=MetricsRunRepository(snapshot),
        artifact_store=ArtifactStoreThatMustNotRead(),
    )

    result = await service.get_run(principal=PRINCIPAL, run_id=RUN_ID)

    assert result.metrics == {"success_rate": 1.0, "latency.p95_ms": 42.0}


async def test_create_run_rejects_same_key_with_different_request() -> None:
    snapshot = RunSnapshot(
        id=RUN_ID,
        dataset_version_id=DATASET_VERSION_ID,
        request_hash="b" * 64,
        status=RunStatus.QUEUED,
        total_jobs=2,
        succeeded_jobs=0,
        failed_jobs=0,
        cancelled_jobs=0,
        created_at=datetime(2026, 7, 29, 13, 0, tzinfo=UTC),
        started_at=None,
        finished_at=None,
    )
    service = SQLAlchemyRunService(
        repository=ReplayRunRepository(snapshot),
        artifact_store=ArtifactStoreThatMustNotRead(),
    )

    with pytest.raises(IdempotencyConflictError):
        await service.create_run(
            principal=PRINCIPAL,
            idempotency_key="create-rag-v1",
            request=make_run_request(),
        )


async def test_create_run_rechecks_hash_after_concurrent_unique_conflict() -> None:
    content = b"\n".join(
        json.dumps(
            {
                "case_id": case_id,
                "question": question,
                "expected_answer": answer,
                "metadata": {},
            },
            separators=(",", ":"),
        ).encode()
        for case_id, question, answer in (
            ("case-1", "q1", "a1"),
            ("case-2", "q2", "a2"),
        )
    )
    repository = ConcurrentWinnerRunRepository(hashlib.sha256(content).hexdigest())
    service = SQLAlchemyRunService(
        repository=repository,
        artifact_store=StaticArtifactStore(content),
    )

    with pytest.raises(IdempotencyConflictError):
        await service.create_run(
            principal=PRINCIPAL,
            idempotency_key="create-rag-v1",
            request=make_run_request(),
        )


async def test_create_run_rejects_invalid_max_attempts_before_dataset_io() -> None:
    request = make_run_request()
    request.evaluator.config["max_attempts"] = 0
    service = SQLAlchemyRunService(
        repository=NewRequestRepositoryThatMustNotLoadSource(),
        artifact_store=ArtifactStoreThatMustNotRead(),
    )

    with pytest.raises(InvalidEvaluatorConfigurationError):
        await service.create_run(
            principal=PRINCIPAL,
            idempotency_key="invalid-attempts",
            request=request,
        )


async def test_create_run_rejects_unsupported_target_before_dataset_io() -> None:
    request = make_run_request()
    request.target.type = "not_supported"
    service = SQLAlchemyRunService(
        repository=NewRequestRepositoryThatMustNotLoadSource(),
        artifact_store=ArtifactStoreThatMustNotRead(),
    )

    with pytest.raises(InvalidTargetConfigurationError):
        await service.create_run(
            principal=PRINCIPAL,
            idempotency_key="invalid-target",
            request=request,
        )


async def test_create_run_rejects_tenant_supplied_http_url_before_dataset_io() -> None:
    request = make_run_request()
    request.target.type = "http_rag"
    request.target.config = {
        "base_url": "https://rag.example.com",
        "endpoint": "/query",
        "allowed_hosts": ["rag.example.com"],
    }
    service = SQLAlchemyRunService(
        repository=NewRequestRepositoryThatMustNotLoadSource(),
        artifact_store=ArtifactStoreThatMustNotRead(),
    )

    with pytest.raises(InvalidTargetConfigurationError):
        await service.create_run(
            principal=PRINCIPAL,
            idempotency_key="tenant-url-is-not-a-registry-reference",
            request=request,
        )


async def test_create_run_snapshots_operator_registered_http_target() -> None:
    content = (
        b'{"case_id":"case-1","question":"q1","expected_answer":"a1","metadata":{}}\n'
        b'{"case_id":"case-2","question":"q2","expected_answer":"a2","metadata":{}}'
    )
    repository = RecordingRunRepository(hashlib.sha256(content).hexdigest())
    registered_config = {
        "base_url": "https://rag.example.com",
        "endpoint": "/v1/query",
        "auth_env_var": "RAG_PRODUCTION_TOKEN",
    }
    service = SQLAlchemyRunService(
        repository=repository,
        artifact_store=StaticArtifactStore(content),
        http_target_registry={
            "rag-production": {
                "version": "rag-v1",
                "config": registered_config,
            }
        },
    )
    request = make_run_request()
    request.target.type = "http_rag"
    request.target.config = {"target_id": "rag-production"}
    request.target.version = "rag-v1"

    await service.create_run(
        principal=PRINCIPAL,
        idempotency_key="create-rag-v1",
        request=request,
    )

    assert repository.new_run is not None
    assert repository.new_run.target_config == {
        **registered_config,
        "target_id": "rag-production",
        "allowed_hosts": ["rag.example.com"],
    }
    assert repository.new_run.target_version == "rag-v1"


async def test_create_run_rejects_unregistered_http_target_before_dataset_io() -> None:
    request = make_run_request()
    request.target.type = "http_rag"
    request.target.config = {"target_id": "not-registered"}
    request.target.version = "rag-v1"
    service = SQLAlchemyRunService(
        repository=NewRequestRepositoryThatMustNotLoadSource(),
        artifact_store=ArtifactStoreThatMustNotRead(),
    )

    with pytest.raises(InvalidTargetConfigurationError):
        await service.create_run(
            principal=PRINCIPAL,
            idempotency_key="unregistered-http-target",
            request=request,
        )


async def test_create_run_rejects_http_target_registry_version_mismatch() -> None:
    request = make_run_request()
    request.target.type = "http_rag"
    request.target.config = {"target_id": "rag-production"}
    request.target.version = "tenant-claimed-v2"
    service = SQLAlchemyRunService(
        repository=NewRequestRepositoryThatMustNotLoadSource(),
        artifact_store=ArtifactStoreThatMustNotRead(),
        http_target_registry={
            "rag-production": {
                "version": "operator-v1",
                "config": {
                    "base_url": "https://rag.example.com",
                    "endpoint": "/v1/query",
                },
            }
        },
    )

    with pytest.raises(InvalidTargetConfigurationError):
        await service.create_run(
            principal=PRINCIPAL,
            idempotency_key="registry-version-mismatch",
            request=request,
        )


async def test_create_run_rejects_unsupported_evaluator_before_dataset_io() -> None:
    request = make_run_request()
    request.evaluator.type = "not_supported"
    service = SQLAlchemyRunService(
        repository=NewRequestRepositoryThatMustNotLoadSource(),
        artifact_store=ArtifactStoreThatMustNotRead(),
    )

    with pytest.raises(InvalidEvaluatorConfigurationError):
        await service.create_run(
            principal=PRINCIPAL,
            idempotency_key="invalid-evaluator",
            request=request,
        )
