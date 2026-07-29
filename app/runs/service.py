from typing import Protocol
from uuid import UUID

from app.artifacts.storage import ArtifactStore
from app.auth.principals import Principal
from app.core.telemetry import Telemetry
from app.datasets.validation import validate_jsonl
from app.evaluators.base import UnsupportedEvaluatorError, build_evaluator
from app.observability.metrics import PlatformMetrics
from app.runs.idempotency import canonical_request_hash
from app.runs.repository import NewRun, RunRepository, RunSnapshot
from app.runs.schemas import RunCreate, RunRead
from app.targets.base import InvalidTargetConfiguration, build_target


class RunService(Protocol):
    async def create_run(
        self,
        *,
        principal: Principal,
        idempotency_key: str,
        request: RunCreate,
    ) -> RunRead:
        """Create or replay a tenant-scoped Evaluation Run."""

    async def get_run(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> RunRead:
        """Return a tenant-owned Run or hide its existence."""


class RunNotFoundError(Exception):
    """Hide absent and cross-tenant Runs behind one outcome."""


class RunDatasetVersionNotFoundError(Exception):
    """The requested dataset version is absent or belongs to another tenant."""


class RunInputIntegrityError(RuntimeError):
    """Dataset metadata and physical content disagree."""


class InvalidEvaluatorConfigurationError(ValueError):
    """Evaluator configuration cannot be converted into Job policy."""


class InvalidTargetConfigurationError(ValueError):
    """Target type or configuration is invalid or unsafe."""


class IdempotencyConflictError(Exception):
    """The same key was already committed for a different canonical request."""


class SQLAlchemyRunService:
    def __init__(
        self,
        *,
        repository: RunRepository,
        artifact_store: ArtifactStore,
        metrics: PlatformMetrics | None = None,
        telemetry: Telemetry | None = None,
    ) -> None:
        self._repository = repository
        self._artifact_store = artifact_store
        self._metrics = metrics
        self._telemetry = telemetry

    async def create_run(
        self,
        *,
        principal: Principal,
        idempotency_key: str,
        request: RunCreate,
    ) -> RunRead:
        request_payload = request.model_dump(mode="json", exclude_none=False)
        request_hash = canonical_request_hash(request_payload)
        existing = await self._repository.find_by_idempotency_key(
            tenant_id=principal.tenant_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise IdempotencyConflictError
            return _to_run_read(existing)

        _validate_components(request)
        max_attempts = _max_attempts(request)
        source = await self._repository.get_dataset_version_source(
            tenant_id=principal.tenant_id,
            dataset_version_id=request.dataset_version_id,
        )
        if source is None:
            raise RunDatasetVersionNotFoundError
        content = await self._artifact_store.get_bytes(source.sha256)
        validated = validate_jsonl(content)
        if validated.sha256 != source.sha256 or validated.case_count != source.case_count:
            raise RunInputIntegrityError

        target_config = dict(request.target.config)
        evaluator_config = dict(request.evaluator.config)
        new_run = NewRun(
            tenant_id=principal.tenant_id,
            created_by=principal.api_key_id,
            dataset_version_id=request.dataset_version_id,
            dataset_hash=source.sha256,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            target_type=request.target.type,
            target_config=target_config,
            target_config_hash=canonical_request_hash(target_config),
            evaluator_type=request.evaluator.type,
            evaluator_config=evaluator_config,
            evaluator_config_hash=canonical_request_hash(evaluator_config),
            target_version=request.target.version,
            evaluator_version=request.evaluator.version,
            source_commit=request.source_commit,
            max_attempts=max_attempts,
            cases=tuple(case.model_dump(mode="json") for case in validated.cases),
        )
        if self._telemetry is None:
            snapshot = await self._repository.create_or_replay(new_run)
        else:
            with self._telemetry.start_as_current_span(
                "run.create.database_transaction",
                attributes={"tenant.id": str(principal.tenant_id)},
            ):
                snapshot = await self._repository.create_or_replay(new_run)
        if snapshot.request_hash != request_hash:
            raise IdempotencyConflictError
        if snapshot.created_now and self._metrics is not None:
            self._metrics.record_run_created()
        return _to_run_read(snapshot)

    async def get_run(
        self,
        *,
        principal: Principal,
        run_id: UUID,
    ) -> RunRead:
        snapshot = await self._repository.get_run(
            tenant_id=principal.tenant_id,
            run_id=run_id,
        )
        if snapshot is None:
            raise RunNotFoundError
        return _to_run_read(snapshot)


def _max_attempts(request: RunCreate) -> int:
    value = request.evaluator.config.get("max_attempts", 3)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10:
        raise InvalidEvaluatorConfigurationError
    return value


def _validate_components(request: RunCreate) -> None:
    try:
        build_target(request.target.type, request.target.config)
    except InvalidTargetConfiguration as error:
        raise InvalidTargetConfigurationError from error
    try:
        build_evaluator(request.evaluator.type, request.evaluator.config)
    except UnsupportedEvaluatorError as error:
        raise InvalidEvaluatorConfigurationError from error


def _to_run_read(snapshot: RunSnapshot) -> RunRead:
    return RunRead(
        id=snapshot.id,
        dataset_version_id=snapshot.dataset_version_id,
        status=snapshot.status,
        total_jobs=snapshot.total_jobs,
        succeeded_jobs=snapshot.succeeded_jobs,
        failed_jobs=snapshot.failed_jobs,
        cancelled_jobs=snapshot.cancelled_jobs,
        created_at=snapshot.created_at,
        started_at=snapshot.started_at,
        finished_at=snapshot.finished_at,
        metrics=snapshot.metrics,
    )
