from sqlalchemy import Table, UniqueConstraint

from app.persistence.orm_models import (
    APIKey,
    Artifact,
    AuditEvent,
    Base,
    CaseResult,
    Dataset,
    DatasetVersion,
    EvaluationJob,
    EvaluationRun,
    JobAttempt,
    RunMetric,
)


def unique_column_sets(table: Table) -> set[frozenset[str]]:
    return {
        frozenset(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def foreign_key_targets(table: Table, column_name: str) -> set[str]:
    column = table.columns[column_name]
    return {foreign_key.target_fullname for foreign_key in column.foreign_keys}


def test_orm_metadata_has_tables_introduced_through_phase_7() -> None:
    assert set(Base.metadata.tables) == {
        "api_keys",
        "artifacts",
        "audit_events",
        "case_results",
        "dataset_versions",
        "datasets",
        "evaluation_jobs",
        "evaluation_runs",
        "job_attempts",
        "run_metrics",
        "tenants",
    }


def test_api_key_metadata_never_defines_a_plaintext_secret_column() -> None:
    columns = set(APIKey.__table__.columns.keys())

    assert {"key_prefix", "key_hash", "status", "expires_at", "last_used_at"} <= columns
    assert {"plaintext", "secret", "api_key"} & columns == set()
    assert frozenset({"key_prefix"}) in unique_column_sets(APIKey.__table__)
    assert foreign_key_targets(APIKey.__table__, "tenant_id") == {"tenants.id"}


def test_dataset_and_version_constraints_encode_identity_and_immutability() -> None:
    assert frozenset({"tenant_id", "name"}) in unique_column_sets(Dataset.__table__)
    assert foreign_key_targets(Dataset.__table__, "tenant_id") == {"tenants.id"}
    assert {
        frozenset({"dataset_id", "version"}),
        frozenset({"dataset_id", "sha256"}),
    } <= unique_column_sets(DatasetVersion.__table__)
    assert foreign_key_targets(DatasetVersion.__table__, "dataset_id") == {"datasets.id"}
    assert foreign_key_targets(DatasetVersion.__table__, "artifact_id") == {"artifacts.id"}


def test_artifact_metadata_is_tenant_owned_while_storage_path_can_be_shared() -> None:
    columns = set(Artifact.__table__.columns.keys())

    assert {
        "tenant_id",
        "artifact_type",
        "sha256",
        "media_type",
        "byte_size",
        "storage_path",
        "run_id",
    } <= columns
    assert "size_bytes" not in columns
    assert foreign_key_targets(Artifact.__table__, "tenant_id") == {"tenants.id"}
    assert foreign_key_targets(Artifact.__table__, "run_id") == {"evaluation_runs.id"}
    assert frozenset({"tenant_id", "artifact_type", "sha256"}) in unique_column_sets(
        Artifact.__table__
    )
    assert frozenset({"storage_path"}) not in unique_column_sets(Artifact.__table__)


def test_run_metrics_are_unique_per_run_and_metric_name() -> None:
    assert frozenset({"run_id", "metric_name"}) in unique_column_sets(RunMetric.__table__)
    assert foreign_key_targets(RunMetric.__table__, "run_id") == {"evaluation_runs.id"}
    assert {"metric_value", "metric_json", "created_at"} <= set(RunMetric.__table__.columns.keys())


def test_run_and_job_constraints_encode_idempotency_and_one_job_per_case() -> None:
    assert "dataset_hash" in EvaluationRun.__table__.columns
    assert "evaluator_type" in EvaluationRun.__table__.columns
    assert frozenset({"tenant_id", "idempotency_key"}) in unique_column_sets(
        EvaluationRun.__table__
    )
    assert foreign_key_targets(EvaluationRun.__table__, "tenant_id") == {"tenants.id"}
    assert foreign_key_targets(EvaluationRun.__table__, "dataset_version_id") == {
        "dataset_versions.id"
    }
    assert frozenset({"run_id", "case_id"}) in unique_column_sets(EvaluationJob.__table__)
    assert foreign_key_targets(EvaluationJob.__table__, "run_id") == {"evaluation_runs.id"}
    assert "case_payload_json" in EvaluationJob.__table__.columns


def test_case_result_is_unique_per_job_and_run_case() -> None:
    assert frozenset({"job_id"}) in unique_column_sets(CaseResult.__table__)
    assert frozenset({"run_id", "case_id"}) in unique_column_sets(CaseResult.__table__)
    assert foreign_key_targets(CaseResult.__table__, "job_id") == {"evaluation_jobs.id"}
    assert foreign_key_targets(CaseResult.__table__, "run_id") == {"evaluation_runs.id"}
    assert "metrics_json" in CaseResult.__table__.columns


def test_attempt_and_audit_metadata_preserve_execution_history() -> None:
    assert frozenset({"job_id", "attempt_number"}) in unique_column_sets(JobAttempt.__table__)
    assert foreign_key_targets(JobAttempt.__table__, "job_id") == {"evaluation_jobs.id"}
    assert foreign_key_targets(AuditEvent.__table__, "tenant_id") == {"tenants.id"}
    assert {"actor_id", "action", "resource_type", "resource_id", "metadata_json"} <= set(
        AuditEvent.__table__.columns.keys()
    )
