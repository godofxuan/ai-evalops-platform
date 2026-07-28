"""Add evaluator identity and idempotent case results.

Revision ID: 20260729_0005
Revises: 20260729_0004
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260729_0005"
down_revision: str | None = "20260729_0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_runs",
        sa.Column(
            "evaluator_type",
            sa.String(length=64),
            server_default="execution",
            nullable=False,
        ),
    )
    op.alter_column("evaluation_runs", "evaluator_type", server_default=None)
    op.create_table(
        "case_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.String(length=200), nullable=False),
        sa.Column(
            "answer_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "evidence_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "metrics_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="input_tokens_nonnegative",
        ),
        sa.CheckConstraint("latency_ms >= 0", name="latency_ms_nonnegative"),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="output_tokens_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["evaluation_jobs.id"],
            name="fk_case_results_job_id_evaluation_jobs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["evaluation_runs.id"],
            name="fk_case_results_run_id_evaluation_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_case_results"),
        sa.UniqueConstraint("job_id", name="uq_case_results_job_id"),
        sa.UniqueConstraint(
            "run_id",
            "case_id",
            name="uq_case_results_run_id_case_id",
        ),
    )
    op.create_index(
        "ix_case_results_run_id_case_id",
        "case_results",
        ["run_id", "case_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_case_results_run_id_case_id", table_name="case_results")
    op.drop_table("case_results")
    op.drop_column("evaluation_runs", "evaluator_type")
