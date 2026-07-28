from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.enums import (
    APIKeyStatus,
    ArtifactType,
    AttemptOutcome,
    JobStatus,
    RunStatus,
    TenantStatus,
)

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

tenant_status_enum = Enum(
    TenantStatus,
    name="tenant_status",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda members: [member.value for member in members],
)
api_key_status_enum = Enum(
    APIKeyStatus,
    name="api_key_status",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda members: [member.value for member in members],
)
artifact_type_enum = Enum(
    ArtifactType,
    name="artifact_type",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda members: [member.value for member in members],
)
run_status_enum = Enum(
    RunStatus,
    name="run_status",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda members: [member.value for member in members],
)
job_status_enum = Enum(
    JobStatus,
    name="job_status",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda members: [member.value for member in members],
)
attempt_outcome_enum = Enum(
    AttemptOutcome,
    name="attempt_outcome",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda members: [member.value for member in members],
)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_tenants_slug"),
        CheckConstraint("char_length(slug) > 0", name="slug_not_empty"),
        CheckConstraint("char_length(name) > 0", name="name_not_empty"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(63), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[TenantStatus] = mapped_column(
        tenant_status_enum,
        nullable=False,
        default=TenantStatus.ACTIVE,
        server_default=TenantStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class APIKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        UniqueConstraint("key_prefix", name="uq_api_keys_key_prefix"),
        CheckConstraint("char_length(name) > 0", name="name_not_empty"),
        Index("ix_api_keys_tenant_id_status", "tenant_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[APIKeyStatus] = mapped_column(
        api_key_status_enum,
        nullable=False,
        default=APIKeyStatus.ACTIVE,
        server_default=APIKeyStatus.ACTIVE.value,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_datasets_tenant_id_name"),
        CheckConstraint("char_length(name) > 0", name="name_not_empty"),
        Index("ix_datasets_tenant_id_id", "tenant_id", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "artifact_type",
            "sha256",
            name="uq_artifacts_tenant_id_artifact_type_sha256",
        ),
        CheckConstraint("byte_size >= 0", name="byte_size_nonnegative"),
        Index("ix_artifacts_tenant_id_created_at", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_type: Mapped[ArtifactType] = mapped_column(
        artifact_type_enum,
        nullable=False,
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "version",
            name="uq_dataset_versions_dataset_id_version",
        ),
        UniqueConstraint(
            "dataset_id",
            "sha256",
            name="uq_dataset_versions_dataset_id_sha256",
        ),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("case_count > 0", name="case_count_positive"),
        Index("ix_dataset_versions_dataset_id_created_at", "dataset_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("artifacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="1",
        server_default="1",
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    case_count: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_evaluation_runs_tenant_id_idempotency_key",
        ),
        CheckConstraint("total_jobs >= 0", name="total_jobs_nonnegative"),
        CheckConstraint("succeeded_jobs >= 0", name="succeeded_jobs_nonnegative"),
        CheckConstraint("failed_jobs >= 0", name="failed_jobs_nonnegative"),
        CheckConstraint("cancelled_jobs >= 0", name="cancelled_jobs_nonnegative"),
        CheckConstraint(
            "succeeded_jobs + failed_jobs + cancelled_jobs <= total_jobs",
            name="terminal_counts_within_total",
        ),
        CheckConstraint("version > 0", name="version_positive"),
        Index(
            "ix_evaluation_runs_tenant_id_status_created_at", "tenant_id", "status", "created_at"
        ),
        Index("ix_evaluation_runs_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    dataset_version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    dataset_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    target_config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluator_type: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluator_config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evaluator_config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_version: Mapped[str] = mapped_column(String(128), nullable=False)
    evaluator_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_commit: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[RunStatus] = mapped_column(
        run_status_enum,
        nullable=False,
        default=RunStatus.QUEUED,
        server_default=RunStatus.QUEUED.value,
    )
    total_jobs: Mapped[int] = mapped_column(nullable=False)
    succeeded_jobs: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    failed_jobs: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    cancelled_jobs: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    created_by: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("api_keys.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")


class EvaluationJob(Base):
    __tablename__ = "evaluation_jobs"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "case_id",
            name="uq_evaluation_jobs_run_id_case_id",
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint("max_attempts > 0", name="max_attempts_positive"),
        CheckConstraint("version > 0", name="version_positive"),
        Index(
            "ix_evaluation_jobs_claim_candidates",
            "status",
            "next_attempt_at",
            "priority",
            "created_at",
        ),
        Index("ix_evaluation_jobs_lease_expires_at", "lease_expires_at"),
        Index("ix_evaluation_jobs_run_id_status", "run_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    case_id: Mapped[str] = mapped_column(String(200), nullable=False)
    case_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        job_status_enum,
        nullable=False,
        default=JobStatus.QUEUED,
        server_default=JobStatus.QUEUED.value,
    )
    priority: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    last_error_message: Mapped[str | None] = mapped_column(String(1_000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")


class JobAttempt(Base):
    __tablename__ = "job_attempts"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "attempt_number",
            name="uq_job_attempts_job_id_attempt_number",
        ),
        CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="latency_ms_nonnegative"),
        Index("ix_job_attempts_job_id_started_at", "job_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("evaluation_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[AttemptOutcome | None] = mapped_column(attempt_outcome_enum)
    retryable: Mapped[bool | None] = mapped_column()
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(1_000))
    upstream_status_code: Mapped[int | None] = mapped_column()
    latency_ms: Mapped[int | None] = mapped_column()
    trace_id: Mapped[str | None] = mapped_column(String(64))


class CaseResult(Base):
    __tablename__ = "case_results"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_case_results_job_id"),
        UniqueConstraint(
            "run_id",
            "case_id",
            name="uq_case_results_run_id_case_id",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="input_tokens_nonnegative",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="output_tokens_nonnegative",
        ),
        CheckConstraint("latency_ms >= 0", name="latency_ms_nonnegative"),
        Index("ix_case_results_run_id_case_id", "run_id", "case_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("evaluation_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    case_id: Mapped[str] = mapped_column(String(200), nullable=False)
    answer_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column()
    output_tokens: Mapped[int | None] = mapped_column()
    latency_ms: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_tenant_id_created_at", "tenant_id", "created_at"),
        Index(
            "ix_audit_events_resource_type_resource_id",
            "resource_type",
            "resource_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
