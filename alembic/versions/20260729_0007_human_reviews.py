"""Add reviewer credential permission and immutable human review history.

Revision ID: 20260729_0007
Revises: 20260729_0006
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260729_0007"
down_revision: str | None = "20260729_0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column(
            "can_review",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.drop_constraint(op.f("ck_artifacts_artifact_type"), "artifacts", type_="check")
    op.create_check_constraint(
        "artifact_type",
        "artifacts",
        "artifact_type IN "
        "('dataset_source', 'run_metrics', 'failure_cases', 'summary_report', "
        "'human_review_packet')",
    )
    op.create_table(
        "human_review_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.String(length=200), nullable=False),
        sa.Column(
            "packet_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "agreed",
                "disputed",
                "adjudicated",
                name="review_task_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["api_keys.id"],
            name="fk_human_review_tasks_created_by_api_keys",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["evaluation_jobs.id"],
            name="fk_human_review_tasks_job_id_evaluation_jobs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["evaluation_runs.id"],
            name="fk_human_review_tasks_run_id_evaluation_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_human_review_tasks_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_human_review_tasks"),
        sa.UniqueConstraint(
            "run_id",
            "case_id",
            name="uq_human_review_tasks_run_id_case_id",
        ),
    )
    op.create_index(
        "ix_human_review_tasks_tenant_id_status_created_at",
        "human_review_tasks",
        ["tenant_id", "status", "created_at"],
        unique=False,
    )
    op.create_table(
        "human_review_submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "labels_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("comment", sa.String(length=1_000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["api_keys.id"],
            name="fk_human_review_submissions_reviewer_id_api_keys",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["human_review_tasks.id"],
            name="fk_human_review_submissions_task_id_human_review_tasks",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_human_review_submissions_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_human_review_submissions"),
        sa.UniqueConstraint(
            "task_id",
            "reviewer_id",
            name="uq_human_review_submissions_task_id_reviewer_id",
        ),
    )
    op.create_index(
        "ix_human_review_submissions_tenant_id_created_at",
        "human_review_submissions",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "human_review_adjudications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("adjudicator_id", sa.Uuid(), nullable=False),
        sa.Column(
            "labels_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("rationale", sa.String(length=2_000), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["adjudicator_id"],
            ["api_keys.id"],
            name="fk_human_review_adjudications_adjudicator_id_api_keys",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["human_review_tasks.id"],
            name="fk_human_review_adjudications_task_id_human_review_tasks",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_human_review_adjudications_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_human_review_adjudications"),
        sa.UniqueConstraint(
            "task_id",
            name="uq_human_review_adjudications_task_id",
        ),
    )
    op.create_index(
        "ix_human_review_adjudications_tenant_id_created_at",
        "human_review_adjudications",
        ["tenant_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_human_review_adjudications_tenant_id_created_at",
        table_name="human_review_adjudications",
    )
    op.drop_table("human_review_adjudications")
    op.drop_index(
        "ix_human_review_submissions_tenant_id_created_at",
        table_name="human_review_submissions",
    )
    op.drop_table("human_review_submissions")
    op.drop_index(
        "ix_human_review_tasks_tenant_id_status_created_at",
        table_name="human_review_tasks",
    )
    op.drop_table("human_review_tasks")
    op.drop_constraint(op.f("ck_artifacts_artifact_type"), "artifacts", type_="check")
    op.create_check_constraint(
        "artifact_type",
        "artifacts",
        "artifact_type IN ('dataset_source', 'run_metrics', 'failure_cases', 'summary_report')",
    )
    op.drop_column("api_keys", "can_review")
