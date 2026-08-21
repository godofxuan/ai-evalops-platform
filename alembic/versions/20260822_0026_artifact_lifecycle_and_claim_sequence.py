"""Add artifact deletion lifecycle and non-blocking scheduler claim sequence."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_0026"
down_revision: str | None = "20260820_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "artifact_blobs",
        sa.Column(
            "lifecycle_status",
            sa.String(length=32),
            nullable=False,
            server_default="ACTIVE",
        ),
    )
    op.add_column("artifact_blobs", sa.Column("deletion_token", sa.Uuid(), nullable=True))
    op.add_column(
        "artifact_blobs",
        sa.Column("deletion_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "artifact_blobs",
        sa.Column("delete_attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "artifact_blobs",
        sa.Column("deletion_error_code", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "artifact_blobs",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "artifact_blobs",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_check_constraint(
        "ck_artifact_blobs_lifecycle_status_known",
        "artifact_blobs",
        "lifecycle_status IN ('ACTIVE', 'DELETE_PENDING', 'DELETED', "
        "'DELETE_FAILED', 'RESTORE_REQUIRED')",
    )
    op.create_check_constraint(
        "ck_artifact_blobs_delete_attempt_count_nonnegative",
        "artifact_blobs",
        "delete_attempt_count >= 0",
    )
    op.create_index(
        "ix_artifact_blobs_reconciliation_lease",
        "artifact_blobs",
        ["lifecycle_status", "deletion_lease_expires_at"],
    )
    op.execute(
        """
        CREATE FUNCTION enforce_artifact_blob_active_reference()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE current_status text;
        BEGIN
            SELECT lifecycle_status INTO current_status
            FROM artifact_blobs
            WHERE sha256 = NEW.blob_sha256
            FOR KEY SHARE;
            IF current_status IS DISTINCT FROM 'ACTIVE' THEN
                RAISE EXCEPTION 'artifact blob % is not ACTIVE', NEW.blob_sha256
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_artifact_references_active_blob
        BEFORE INSERT OR UPDATE OF blob_sha256 ON artifact_references
        FOR EACH ROW
        EXECUTE FUNCTION enforce_artifact_blob_active_reference();
        """
    )
    op.create_table(
        "mcp_audit_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("api_key_id", sa.Uuid(), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("call_identity", sa.String(length=255), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=False),
        sa.Column("outcome_status", sa.String(length=32), nullable=True),
        sa.Column(
            "delivery_status",
            sa.String(length=16),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "delivery_status IN ('PENDING', 'DELIVERED')",
            name="ck_mcp_audit_outbox_delivery_status_known",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_mcp_audit_outbox_attempt_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_mcp_audit_outbox_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mcp_audit_outbox"),
        sa.UniqueConstraint("trace_id", name="uq_mcp_audit_outbox_trace_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "tool_name",
            "call_identity",
            name="uq_mcp_audit_outbox_call_identity",
        ),
    )
    op.create_index(
        "ix_mcp_audit_outbox_pending",
        "mcp_audit_outbox",
        ["delivery_status", "created_at"],
    )
    op.execute("CREATE SEQUENCE scheduler_claim_receipt_seq AS BIGINT START WITH 1")
    op.execute(
        "SELECT setval('scheduler_claim_receipt_seq', GREATEST(1, "
        "COALESCE((SELECT MAX(scheduler_claim_sequence) FROM job_attempts), 0), "
        "COALESCE((SELECT durable_claim_sequence FROM scheduler_coordination WHERE id = 1), 0)), "
        "COALESCE((SELECT MAX(scheduler_claim_sequence) FROM job_attempts), 0) > 0 OR "
        "COALESCE((SELECT durable_claim_sequence FROM scheduler_coordination WHERE id = 1), 0) > 0)"
    )


def downgrade() -> None:
    op.execute("DROP SEQUENCE scheduler_claim_receipt_seq")
    op.drop_table("mcp_audit_outbox")
    op.execute("DROP TRIGGER trg_artifact_references_active_blob ON artifact_references")
    op.execute("DROP FUNCTION enforce_artifact_blob_active_reference()")
    op.drop_index("ix_artifact_blobs_reconciliation_lease", table_name="artifact_blobs")
    op.drop_constraint(
        "ck_artifact_blobs_delete_attempt_count_nonnegative",
        "artifact_blobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_artifact_blobs_lifecycle_status_known",
        "artifact_blobs",
        type_="check",
    )
    op.drop_column("artifact_blobs", "updated_at")
    op.drop_column("artifact_blobs", "deleted_at")
    op.drop_column("artifact_blobs", "deletion_error_code")
    op.drop_column("artifact_blobs", "delete_attempt_count")
    op.drop_column("artifact_blobs", "deletion_lease_expires_at")
    op.drop_column("artifact_blobs", "deletion_token")
    op.drop_column("artifact_blobs", "lifecycle_status")
