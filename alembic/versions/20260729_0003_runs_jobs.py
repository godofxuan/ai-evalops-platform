"""Create Phase 2 Evaluation Run and Job tables.

Revision ID: 20260729_0003
Revises: 20260729_0002
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260729_0003"
down_revision: str | None = "20260729_0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("target_config_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "evaluator_config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("evaluator_config_hash", sa.String(length=64), nullable=False),
        sa.Column("target_version", sa.String(length=128), nullable=False),
        sa.Column("evaluator_version", sa.String(length=128), nullable=False),
        sa.Column("source_commit", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "partially_succeeded",
                "failed",
                "cancelling",
                "cancelled",
                name="run_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("total_jobs", sa.Integer(), nullable=False),
        sa.Column("succeeded_jobs", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_jobs", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cancelled_jobs", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("cancelled_jobs >= 0", name="cancelled_jobs_nonnegative"),
        sa.CheckConstraint("failed_jobs >= 0", name="failed_jobs_nonnegative"),
        sa.CheckConstraint("succeeded_jobs >= 0", name="succeeded_jobs_nonnegative"),
        sa.CheckConstraint(
            "succeeded_jobs + failed_jobs + cancelled_jobs <= total_jobs",
            name="terminal_counts_within_total",
        ),
        sa.CheckConstraint("total_jobs >= 0", name="total_jobs_nonnegative"),
        sa.CheckConstraint("version > 0", name="version_positive"),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["api_keys.id"],
            name="fk_evaluation_runs_created_by_api_keys",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_versions.id"],
            name="fk_evaluation_runs_dataset_version_id_dataset_versions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_evaluation_runs_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evaluation_runs"),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_evaluation_runs_tenant_id_idempotency_key",
        ),
    )
    op.create_index(
        "ix_evaluation_runs_dataset_version_id",
        "evaluation_runs",
        ["dataset_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_runs_tenant_id_status_created_at",
        "evaluation_runs",
        ["tenant_id", "status", "created_at"],
        unique=False,
    )

    op.create_table(
        "evaluation_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.String(length=200), nullable=False),
        sa.Column("case_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "retry_wait",
                "succeeded",
                "failed",
                "cancelling",
                "cancelled",
                name="job_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error_message", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        sa.CheckConstraint("max_attempts > 0", name="max_attempts_positive"),
        sa.CheckConstraint("version > 0", name="version_positive"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["evaluation_runs.id"],
            name="fk_evaluation_jobs_run_id_evaluation_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evaluation_jobs"),
        sa.UniqueConstraint(
            "run_id",
            "case_id",
            name="uq_evaluation_jobs_run_id_case_id",
        ),
    )
    op.create_index(
        "ix_evaluation_jobs_claim_candidates",
        "evaluation_jobs",
        ["status", "next_attempt_at", "priority", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_jobs_lease_expires_at",
        "evaluation_jobs",
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_jobs_run_id_status",
        "evaluation_jobs",
        ["run_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_evaluation_jobs_run_id_status", table_name="evaluation_jobs")
    op.drop_index("ix_evaluation_jobs_lease_expires_at", table_name="evaluation_jobs")
    op.drop_index("ix_evaluation_jobs_claim_candidates", table_name="evaluation_jobs")
    op.drop_table("evaluation_jobs")
    op.drop_index(
        "ix_evaluation_runs_tenant_id_status_created_at",
        table_name="evaluation_runs",
    )
    op.drop_index(
        "ix_evaluation_runs_dataset_version_id",
        table_name="evaluation_runs",
    )
    op.drop_table("evaluation_runs")
