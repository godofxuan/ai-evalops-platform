from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Table, UniqueConstraint

from app.persistence.orm_models import (
    AgentEvaluationResultRecord,
    AgentExecutionArtifact,
    APIKey,
    ArtifactBlob,
    ArtifactReference,
    AuditEvent,
    Base,
    CaseResult,
    Dataset,
    DatasetVersion,
    EvaluationJob,
    EvaluationRun,
    HumanReviewAdjudication,
    HumanReviewSubmission,
    HumanReviewTask,
    JobAttempt,
    ProgressEventOutbox,
    RunMetric,
    SchedulerCoordination,
    Tenant,
    TenantSchedulerState,
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


def foreign_key_specs(
    table: Table,
) -> set[tuple[tuple[str, ...], tuple[str, ...]]]:
    return {
        (
            tuple(element.parent.name for element in constraint.elements),
            tuple(element.target_fullname for element in constraint.elements),
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def check_expressions(table: Table) -> set[str]:
    return {
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_orm_metadata_has_current_tables_through_p2_1() -> None:
    assert set(Base.metadata.tables) == {
        "api_keys",
        "agent_evaluation_results",
        "agent_execution_artifacts",
        "agent_regression_comparisons",
        "agent_regression_evidence",
        "artifact_blobs",
        "artifact_reconciliation_events",
        "artifact_references",
        "audit_events",
        "case_results",
        "dataset_versions",
        "datasets",
        "evaluation_jobs",
        "evaluation_runs",
        "human_review_adjudications",
        "human_review_submissions",
        "human_review_tasks",
        "job_attempts",
        "mcp_audit_outbox",
        "progress_event_outbox",
        "run_metrics",
        "scheduler_coordination",
        "tenant_scheduler_states",
        "tenants",
    }


def test_agent_evaluation_results_keep_tenant_run_and_artifact_lineage() -> None:
    assert frozenset({"id", "tenant_id", "run_id"}) in unique_column_sets(
        AgentExecutionArtifact.__table__
    )
    assert (
        ("artifact_id", "tenant_id", "run_id"),
        (
            "agent_execution_artifacts.id",
            "agent_execution_artifacts.tenant_id",
            "agent_execution_artifacts.run_id",
        ),
    ) in foreign_key_specs(AgentEvaluationResultRecord.__table__)
    assert frozenset(
        {"artifact_id", "evaluator_kind", "evaluator_version", "config_sha256"}
    ) in unique_column_sets(AgentEvaluationResultRecord.__table__)


def test_tenant_metadata_includes_fair_claim_scheduling_state() -> None:
    assert "last_scheduler_turn_at" in Tenant.__table__.columns
    assert "ix_tenants_last_scheduler_turn_at" in {index.name for index in Tenant.__table__.indexes}


def test_candidate3_scheduler_state_is_bounded_and_tenant_owned() -> None:
    assert set(SchedulerCoordination.__table__.columns.keys()) >= {
        "id",
        "active_generation",
        "active_priority",
        "durable_claim_sequence",
        "version",
    }
    assert foreign_key_targets(TenantSchedulerState.__table__, "tenant_id") == {"tenants.id"}
    assert frozenset({"generation", "tenant_id"}) in unique_column_sets(
        TenantSchedulerState.__table__
    )
    assert {
        "generation > 0",
        "permit_order > 0",
        "status IN ('pending', 'consumed', 'empty')",
        "version > 0",
    } <= check_expressions(TenantSchedulerState.__table__)
    assert "ix_tenant_scheduler_states_active_permits" in {
        index.name for index in TenantSchedulerState.__table__.indexes
    }


def test_job_attempt_claim_sequence_is_nullable_unique_and_positive() -> None:
    sequence = JobAttempt.__table__.columns.scheduler_claim_sequence
    assert sequence.nullable
    assert frozenset({"scheduler_claim_sequence"}) in unique_column_sets(JobAttempt.__table__)
    assert "scheduler_claim_sequence IS NULL OR scheduler_claim_sequence > 0" in check_expressions(
        JobAttempt.__table__
    )


def test_api_key_metadata_never_defines_a_plaintext_secret_column() -> None:
    columns = set(APIKey.__table__.columns.keys())

    assert {
        "key_prefix",
        "key_hash",
        "status",
        "expires_at",
        "last_used_at",
        "can_create_review_tasks",
    } <= columns
    assert {"plaintext", "secret", "api_key"} & columns == set()
    assert frozenset({"key_prefix"}) in unique_column_sets(APIKey.__table__)
    assert foreign_key_targets(APIKey.__table__, "tenant_id") == {"tenants.id"}
    task_creator = APIKey.__table__.columns.can_create_review_tasks
    assert not task_creator.nullable
    assert task_creator.default is not None
    assert task_creator.default.arg is False
    assert task_creator.server_default is not None
    assert str(task_creator.server_default.arg) == "false"


def test_evaluation_run_origin_traceparent_is_nullable_and_bounded() -> None:
    origin_traceparent = EvaluationRun.__table__.columns.origin_traceparent

    assert origin_traceparent.nullable
    assert origin_traceparent.type.length == 55
    assert origin_traceparent.default is None
    assert origin_traceparent.server_default is None


def test_progress_event_outbox_is_tenant_scoped_leased_and_append_only() -> None:
    columns = ProgressEventOutbox.__table__.columns

    assert set(columns.keys()) == {
        "id",
        "tenant_id",
        "run_id",
        "event_type",
        "payload_json",
        "occurred_at",
        "available_at",
        "attempt_count",
        "lease_owner",
        "lease_expires_at",
        "published_at",
        "last_error_code",
        "created_at",
    }
    assert (
        ("run_id", "tenant_id"),
        ("evaluation_runs.id", "evaluation_runs.tenant_id"),
    ) in foreign_key_specs(ProgressEventOutbox.__table__)
    assert any(
        "attempt_count >= 0" in expression
        for expression in check_expressions(ProgressEventOutbox.__table__)
    )
    indexes = {index.name: index for index in ProgressEventOutbox.__table__.indexes}
    retention_index = indexes["ix_progress_event_outbox_published_retention"]
    assert tuple(column.name for column in retention_index.columns) == ("published_at", "id")
    assert str(retention_index.dialect_options["postgresql"]["where"]) == (
        "published_at IS NOT NULL"
    )


def test_dataset_and_version_constraints_encode_identity_and_immutability() -> None:
    assert frozenset({"tenant_id", "name"}) in unique_column_sets(Dataset.__table__)
    assert foreign_key_targets(Dataset.__table__, "tenant_id") == {"tenants.id"}
    assert {
        frozenset({"dataset_id", "version"}),
        frozenset({"dataset_id", "sha256"}),
    } <= unique_column_sets(DatasetVersion.__table__)
    assert foreign_key_targets(DatasetVersion.__table__, "dataset_id") == {"datasets.id"}
    assert foreign_key_targets(DatasetVersion.__table__, "artifact_id") == {
        "artifact_references.id"
    }


def test_artifact_blob_and_reference_metadata_separate_content_from_ownership() -> None:
    assert set(ArtifactBlob.__table__.columns.keys()) == {
        "sha256",
        "byte_size",
        "storage_path",
        "lifecycle_status",
        "deletion_token",
        "deletion_lease_expires_at",
        "delete_attempt_count",
        "deletion_error_code",
        "deleted_at",
        "created_at",
        "updated_at",
    }
    assert foreign_key_targets(ArtifactReference.__table__, "blob_sha256") == {
        "artifact_blobs.sha256"
    }
    assert "tenants.id" in foreign_key_targets(ArtifactReference.__table__, "tenant_id")
    assert foreign_key_targets(ArtifactReference.__table__, "run_id") == {"evaluation_runs.id"}
    assert {
        "id",
        "blob_sha256",
        "tenant_id",
        "run_id",
        "artifact_type",
        "media_type",
        "created_at",
    } == set(ArtifactReference.__table__.columns.keys())
    assert frozenset({"tenant_id", "run_id", "artifact_type", "blob_sha256"}) in unique_column_sets(
        ArtifactReference.__table__
    )
    assert any(
        "artifact_type = 'dataset_source' AND run_id IS NULL" in expression
        and "artifact_type <> 'dataset_source' AND run_id IS NOT NULL" in expression
        for expression in check_expressions(ArtifactReference.__table__)
    )
    assert foreign_key_targets(DatasetVersion.__table__, "artifact_id") == {
        "artifact_references.id"
    }


def test_dataset_artifact_and_run_share_one_tenant_lineage() -> None:
    assert "tenant_id" in DatasetVersion.__table__.columns
    assert not DatasetVersion.__table__.columns.tenant_id.nullable
    assert frozenset({"id", "tenant_id"}) in unique_column_sets(Dataset.__table__)
    assert frozenset({"id", "tenant_id"}) in unique_column_sets(ArtifactReference.__table__)
    assert frozenset({"id", "tenant_id"}) in unique_column_sets(DatasetVersion.__table__)
    assert frozenset({"id", "tenant_id"}) in unique_column_sets(EvaluationRun.__table__)

    assert (
        ("dataset_id", "tenant_id"),
        ("datasets.id", "datasets.tenant_id"),
    ) in foreign_key_specs(DatasetVersion.__table__)
    assert (
        ("artifact_id", "tenant_id"),
        ("artifact_references.id", "artifact_references.tenant_id"),
    ) in foreign_key_specs(DatasetVersion.__table__)
    assert (
        ("dataset_version_id", "tenant_id"),
        ("dataset_versions.id", "dataset_versions.tenant_id"),
    ) in foreign_key_specs(EvaluationRun.__table__)
    assert (
        ("run_id", "tenant_id"),
        ("evaluation_runs.id", "evaluation_runs.tenant_id"),
    ) in foreign_key_specs(ArtifactReference.__table__)


def test_run_and_human_review_actors_share_the_record_tenant() -> None:
    assert frozenset({"id", "tenant_id"}) in unique_column_sets(APIKey.__table__)
    assert frozenset({"id", "tenant_id"}) in unique_column_sets(HumanReviewTask.__table__)

    assert (
        ("created_by", "tenant_id"),
        ("api_keys.id", "api_keys.tenant_id"),
    ) in foreign_key_specs(EvaluationRun.__table__)
    assert (
        ("run_id", "tenant_id"),
        ("evaluation_runs.id", "evaluation_runs.tenant_id"),
    ) in foreign_key_specs(HumanReviewTask.__table__)
    assert (
        ("created_by", "tenant_id"),
        ("api_keys.id", "api_keys.tenant_id"),
    ) in foreign_key_specs(HumanReviewTask.__table__)
    assert (
        ("task_id", "tenant_id"),
        ("human_review_tasks.id", "human_review_tasks.tenant_id"),
    ) in foreign_key_specs(HumanReviewSubmission.__table__)
    assert (
        ("reviewer_id", "tenant_id"),
        ("api_keys.id", "api_keys.tenant_id"),
    ) in foreign_key_specs(HumanReviewSubmission.__table__)
    assert (
        ("task_id", "tenant_id"),
        ("human_review_tasks.id", "human_review_tasks.tenant_id"),
    ) in foreign_key_specs(HumanReviewAdjudication.__table__)


def test_case_results_and_review_tasks_share_their_jobs_run() -> None:
    assert frozenset({"id", "run_id"}) in unique_column_sets(EvaluationJob.__table__)
    assert (
        ("job_id", "run_id"),
        ("evaluation_jobs.id", "evaluation_jobs.run_id"),
    ) in foreign_key_specs(CaseResult.__table__)
    assert not CaseResult.__table__.columns.tenant_id.nullable
    assert (
        ("run_id", "tenant_id"),
        ("evaluation_runs.id", "evaluation_runs.tenant_id"),
    ) in foreign_key_specs(CaseResult.__table__)
    assert (
        ("job_id", "run_id"),
        ("evaluation_jobs.id", "evaluation_jobs.run_id"),
    ) in foreign_key_specs(HumanReviewTask.__table__)
    assert (
        ("adjudicator_id", "tenant_id"),
        ("api_keys.id", "api_keys.tenant_id"),
    ) in foreign_key_specs(HumanReviewAdjudication.__table__)


def test_run_metrics_are_unique_per_run_and_metric_name() -> None:
    assert frozenset({"run_id", "metric_name"}) in unique_column_sets(RunMetric.__table__)
    assert foreign_key_targets(RunMetric.__table__, "run_id") == {"evaluation_runs.id"}
    assert {"metric_value", "metric_json", "created_at"} <= set(RunMetric.__table__.columns.keys())


def test_human_review_history_is_tenant_owned_and_immutable_by_constraint() -> None:
    assert frozenset(
        {"tenant_id", "source_type", "source_record_id", "packet_schema_version"}
    ) in unique_column_sets(HumanReviewTask.__table__)
    assert frozenset({"task_id", "reviewer_id"}) in unique_column_sets(
        HumanReviewSubmission.__table__
    )
    assert frozenset({"task_id"}) in unique_column_sets(HumanReviewAdjudication.__table__)
    for table in (
        HumanReviewTask.__table__,
        HumanReviewSubmission.__table__,
        HumanReviewAdjudication.__table__,
    ):
        assert "tenants.id" in foreign_key_targets(table, "tenant_id")


def test_run_and_job_constraints_encode_idempotency_and_one_job_per_case() -> None:
    assert "dataset_hash" in EvaluationRun.__table__.columns
    assert "evaluator_type" in EvaluationRun.__table__.columns
    assert frozenset({"tenant_id", "idempotency_key"}) in unique_column_sets(
        EvaluationRun.__table__
    )
    assert "tenants.id" in foreign_key_targets(EvaluationRun.__table__, "tenant_id")
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
    assert foreign_key_targets(CaseResult.__table__, "run_id") == {
        "evaluation_jobs.run_id",
        "evaluation_runs.id",
    }
    assert foreign_key_targets(CaseResult.__table__, "tenant_id") == {
        "evaluation_runs.tenant_id",
        "tenants.id",
    }
    assert "metrics_json" in CaseResult.__table__.columns


def test_attempt_and_audit_metadata_preserve_execution_history() -> None:
    assert frozenset({"job_id", "attempt_number"}) in unique_column_sets(JobAttempt.__table__)
    assert foreign_key_targets(JobAttempt.__table__, "job_id") == {"evaluation_jobs.id"}
    assert foreign_key_targets(AuditEvent.__table__, "tenant_id") == {"tenants.id"}
    assert {"actor_id", "action", "resource_type", "resource_id", "metadata_json"} <= set(
        AuditEvent.__table__.columns.keys()
    )
