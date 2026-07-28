"""Add immutable attempt history and transition audit events.

Revision ID: 20260729_0004
Revises: 20260729_0003
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260729_0004"
down_revision: str | None = "20260729_0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "job_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum(
                "succeeded",
                "failed",
                "cancelled",
                "lease_expired",
                name="attempt_outcome",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("retryable", sa.Boolean(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("upstream_status_code", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="latency_ms_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["evaluation_jobs.id"],
            name="fk_job_attempts_job_id_evaluation_jobs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_job_attempts"),
        sa.UniqueConstraint(
            "job_id",
            "attempt_number",
            name="uq_job_attempts_job_id_attempt_number",
        ),
    )
    op.create_index(
        "ix_job_attempts_job_id_started_at",
        "job_attempts",
        ["job_id", "started_at"],
        unique=False,
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_audit_events_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index(
        "ix_audit_events_resource_type_resource_id",
        "audit_events",
        ["resource_type", "resource_id"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_tenant_id_created_at",
        "audit_events",
        ["tenant_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_tenant_id_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_resource_type_resource_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_job_attempts_job_id_started_at", table_name="job_attempts")
    op.drop_table("job_attempts")
