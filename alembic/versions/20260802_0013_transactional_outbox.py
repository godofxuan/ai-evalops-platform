"""Add a durable transactional outbox for progress notifications.

Revision ID: 20260802_0013
Revises: 20260802_0012
Create Date: 2026-08-02
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260802_0013"
down_revision: str | None = "20260802_0012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "progress_event_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_progress_event_outbox_attempt_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
            name=op.f("ck_progress_event_outbox_lease_fields_consistent"),
        ),
        sa.CheckConstraint(
            "published_at IS NULL OR (lease_owner IS NULL AND lease_expires_at IS NULL)",
            name=op.f("ck_progress_event_outbox_published_event_not_leased"),
        ),
        sa.CheckConstraint(
            "event_type IN ('run_started', 'job_progress', 'job_failed', "
            "'job_retried', 'run_completed')",
            name=op.f("ck_progress_event_outbox_event_type_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "tenant_id"],
            ["evaluation_runs.id", "evaluation_runs.tenant_id"],
            name=op.f("fk_progress_event_outbox_run_id_tenant_id_evaluation_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_progress_event_outbox")),
    )
    op.create_index(
        "ix_progress_event_outbox_pending",
        "progress_event_outbox",
        ["available_at", "created_at", "id"],
        unique=False,
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_index(
        "ix_progress_event_outbox_tenant_id_run_id_created_at",
        "progress_event_outbox",
        ["tenant_id", "run_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_progress_event_outbox_tenant_id_run_id_created_at",
        table_name="progress_event_outbox",
    )
    op.drop_index(
        "ix_progress_event_outbox_pending",
        table_name="progress_event_outbox",
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.drop_table("progress_event_outbox")
