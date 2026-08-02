"""Separate content-addressed artifact blobs from tenant-owned references.

Revision ID: 20260802_0009
Revises: 20260729_0008
Create Date: 2026-08-02
"""

import sqlalchemy as sa

from alembic import op

revision: str = "20260802_0009"
down_revision: str | None = "20260729_0008"
branch_labels: str | None = None
depends_on: str | None = None


ARTIFACT_TYPE_CHECK = (
    "artifact_type IN "
    "('dataset_source', 'run_metrics', 'failure_cases', "
    "'summary_report', 'human_review_packet')"
)


def upgrade() -> None:
    op.create_table(
        "artifact_blobs",
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("byte_size >= 0", name="byte_size_nonnegative"),
        sa.PrimaryKeyConstraint("sha256", name="pk_artifact_blobs"),
        sa.UniqueConstraint(
            "storage_path",
            name="uq_artifact_blobs_storage_path",
        ),
    )
    op.create_table(
        "artifact_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("blob_sha256", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(ARTIFACT_TYPE_CHECK, name="artifact_type"),
        sa.CheckConstraint(
            "(artifact_type = 'dataset_source' AND run_id IS NULL) OR "
            "(artifact_type <> 'dataset_source' AND run_id IS NOT NULL)",
            name="owner_scope",
        ),
        sa.ForeignKeyConstraint(
            ["blob_sha256"],
            ["artifact_blobs.sha256"],
            name="fk_artifact_references_blob_sha256_artifact_blobs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["evaluation_runs.id"],
            name="fk_artifact_references_run_id_evaluation_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_artifact_references_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_artifact_references"),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "artifact_type",
            "blob_sha256",
            name="uq_artifact_references_owner_type_blob",
        ),
    )
    op.create_index(
        "ix_artifact_references_tenant_id_created_at",
        "artifact_references",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_artifact_references_run_id_artifact_type",
        "artifact_references",
        ["run_id", "artifact_type"],
        unique=False,
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM artifacts
                WHERE NOT (
                    (artifact_type = 'dataset_source' AND run_id IS NULL)
                    OR (artifact_type <> 'dataset_source' AND run_id IS NOT NULL)
                )
            ) THEN
                RAISE EXCEPTION
                    'artifact backfill found inconsistent Run ownership scope';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM artifacts
                GROUP BY sha256
                HAVING COUNT(DISTINCT byte_size) > 1
                    OR COUNT(DISTINCT storage_path) > 1
            ) THEN
                RAISE EXCEPTION
                    'artifact blob backfill found conflicting metadata for one sha256';
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        INSERT INTO artifact_blobs (sha256, byte_size, storage_path, created_at)
        SELECT sha256, MIN(byte_size), MIN(storage_path), MIN(created_at)
        FROM artifacts
        GROUP BY sha256
        """
    )
    op.execute(
        """
        INSERT INTO artifact_references (
            id,
            blob_sha256,
            tenant_id,
            run_id,
            artifact_type,
            media_type,
            created_at
        )
        SELECT id, sha256, tenant_id, run_id, artifact_type, media_type, created_at
        FROM artifacts
        """
    )

    op.drop_constraint(
        "fk_dataset_versions_artifact_id_artifacts",
        "dataset_versions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_dataset_versions_artifact_id_artifact_references",
        "dataset_versions",
        "artifact_references",
        ["artifact_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_table("artifacts")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM artifact_references
                GROUP BY tenant_id, artifact_type, blob_sha256
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'artifact downgrade would lose distinct ownership references';
            END IF;
        END
        $$
        """
    )

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(ARTIFACT_TYPE_CHECK, name="artifact_type"),
        sa.CheckConstraint("byte_size >= 0", name="byte_size_nonnegative"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["evaluation_runs.id"],
            name="fk_artifacts_run_id_evaluation_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_artifacts_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_artifacts"),
        sa.UniqueConstraint(
            "tenant_id",
            "artifact_type",
            "sha256",
            name="uq_artifacts_tenant_id_artifact_type_sha256",
        ),
    )
    op.create_index(
        "ix_artifacts_tenant_id_created_at",
        "artifacts",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_artifacts_run_id_artifact_type",
        "artifacts",
        ["run_id", "artifact_type"],
        unique=False,
    )
    op.execute(
        """
        INSERT INTO artifacts (
            id,
            tenant_id,
            run_id,
            artifact_type,
            sha256,
            media_type,
            byte_size,
            storage_path,
            created_at
        )
        SELECT
            artifact_references.id,
            artifact_references.tenant_id,
            artifact_references.run_id,
            artifact_references.artifact_type,
            artifact_references.blob_sha256,
            artifact_references.media_type,
            artifact_blobs.byte_size,
            artifact_blobs.storage_path,
            artifact_references.created_at
        FROM artifact_references
        JOIN artifact_blobs
            ON artifact_blobs.sha256 = artifact_references.blob_sha256
        """
    )

    op.drop_constraint(
        "fk_dataset_versions_artifact_id_artifact_references",
        "dataset_versions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_dataset_versions_artifact_id_artifacts",
        "dataset_versions",
        "artifacts",
        ["artifact_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_table("artifact_references")
    op.drop_table("artifact_blobs")
