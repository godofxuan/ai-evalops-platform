"""Enforce cross-table tenant and parent-lineage consistency.

Revision ID: 20260802_0010
Revises: 20260802_0009
Create Date: 2026-08-02
"""

import sqlalchemy as sa

from alembic import op

revision: str = "20260802_0010"
down_revision: str | None = "20260802_0009"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "dataset_versions",
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM dataset_versions AS dv
                JOIN datasets AS d ON d.id = dv.dataset_id
                JOIN artifact_references AS ar ON ar.id = dv.artifact_id
                WHERE d.tenant_id <> ar.tenant_id
            ) THEN
                RAISE EXCEPTION
                    'tenant consistency check failed: dataset/artifact tenant mismatch';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM evaluation_runs AS r
                JOIN dataset_versions AS dv ON dv.id = r.dataset_version_id
                JOIN datasets AS d ON d.id = dv.dataset_id
                WHERE r.tenant_id <> d.tenant_id
            ) THEN
                RAISE EXCEPTION
                    'tenant consistency check failed: run/dataset-version tenant mismatch';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM evaluation_runs AS r
                JOIN api_keys AS k ON k.id = r.created_by
                WHERE r.tenant_id <> k.tenant_id
            ) THEN
                RAISE EXCEPTION
                    'tenant consistency check failed: run/creator tenant mismatch';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM artifact_references AS ar
                JOIN evaluation_runs AS r ON r.id = ar.run_id
                WHERE ar.tenant_id <> r.tenant_id
            ) THEN
                RAISE EXCEPTION
                    'tenant consistency check failed: artifact/run tenant mismatch';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM case_results AS cr
                JOIN evaluation_jobs AS j ON j.id = cr.job_id
                WHERE cr.run_id <> j.run_id
            ) THEN
                RAISE EXCEPTION
                    'tenant consistency check failed: case-result job/run mismatch';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM human_review_tasks AS t
                JOIN evaluation_runs AS r ON r.id = t.run_id
                WHERE t.tenant_id <> r.tenant_id
            ) THEN
                RAISE EXCEPTION
                    'tenant consistency check failed: human-review task/run tenant mismatch';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM human_review_tasks AS t
                JOIN evaluation_jobs AS j ON j.id = t.job_id
                WHERE t.run_id <> j.run_id
            ) THEN
                RAISE EXCEPTION
                    'tenant consistency check failed: human-review task job/run mismatch';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM human_review_tasks AS t
                JOIN api_keys AS k ON k.id = t.created_by
                WHERE t.tenant_id <> k.tenant_id
            ) THEN
                RAISE EXCEPTION
                    'tenant consistency check failed: human-review task/creator tenant mismatch';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM human_review_submissions AS s
                JOIN human_review_tasks AS t ON t.id = s.task_id
                WHERE s.tenant_id <> t.tenant_id
            ) THEN
                RAISE EXCEPTION
                    'tenant consistency check failed: human-review submission/task tenant mismatch';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM human_review_submissions AS s
                JOIN api_keys AS k ON k.id = s.reviewer_id
                WHERE s.tenant_id <> k.tenant_id
            ) THEN
                RAISE EXCEPTION
                    'tenant check failed: review submission/reviewer tenant mismatch';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM human_review_adjudications AS a
                JOIN human_review_tasks AS t ON t.id = a.task_id
                WHERE a.tenant_id <> t.tenant_id
            ) THEN
                RAISE EXCEPTION
                    'tenant check failed: review adjudication/task tenant mismatch';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM human_review_adjudications AS a
                JOIN api_keys AS k ON k.id = a.adjudicator_id
                WHERE a.tenant_id <> k.tenant_id
            ) THEN
                RAISE EXCEPTION
                    'tenant check failed: review adjudication/adjudicator tenant mismatch';
            END IF;
        END
        $$
        """
    )

    op.execute(
        """
        UPDATE dataset_versions AS dv
        SET tenant_id = datasets.tenant_id
        FROM datasets
        WHERE datasets.id = dv.dataset_id
        """
    )
    op.alter_column(
        "dataset_versions",
        "tenant_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )

    for table_name, columns, constraint_name in (
        ("api_keys", ["id", "tenant_id"], "uq_api_keys_id_tenant_id"),
        ("datasets", ["id", "tenant_id"], "uq_datasets_id_tenant_id"),
        (
            "artifact_references",
            ["id", "tenant_id"],
            "uq_artifact_references_id_tenant_id",
        ),
        (
            "dataset_versions",
            ["id", "tenant_id"],
            "uq_dataset_versions_id_tenant_id",
        ),
        (
            "evaluation_runs",
            ["id", "tenant_id"],
            "uq_evaluation_runs_id_tenant_id",
        ),
        (
            "evaluation_jobs",
            ["id", "run_id"],
            "uq_evaluation_jobs_id_run_id",
        ),
        (
            "human_review_tasks",
            ["id", "tenant_id"],
            "uq_human_review_tasks_id_tenant_id",
        ),
    ):
        op.create_unique_constraint(constraint_name, table_name, columns)

    op.drop_constraint(
        "fk_artifact_references_run_id_evaluation_runs",
        "artifact_references",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_artifact_references_run_id_tenant_id_evaluation_runs",
        "artifact_references",
        "evaluation_runs",
        ["run_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "fk_dataset_versions_dataset_id_datasets",
        "dataset_versions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_dataset_versions_artifact_id_artifact_references",
        "dataset_versions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_dataset_versions_dataset_id_tenant_id_datasets",
        "dataset_versions",
        "datasets",
        ["dataset_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_dataset_versions_artifact_id_tenant_id_artifact_references",
        "dataset_versions",
        "artifact_references",
        ["artifact_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        "fk_evaluation_runs_dataset_version_id_dataset_versions",
        "evaluation_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_evaluation_runs_created_by_api_keys",
        "evaluation_runs",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_evaluation_runs_dataset_version_tenant",
        "evaluation_runs",
        "dataset_versions",
        ["dataset_version_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_evaluation_runs_created_by_tenant_id_api_keys",
        "evaluation_runs",
        "api_keys",
        ["created_by", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        "fk_case_results_job_id_evaluation_jobs",
        "case_results",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_case_results_run_id_evaluation_runs",
        "case_results",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_case_results_job_id_run_id_evaluation_jobs",
        "case_results",
        "evaluation_jobs",
        ["job_id", "run_id"],
        ["id", "run_id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "fk_human_review_tasks_run_id_evaluation_runs",
        "human_review_tasks",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_human_review_tasks_job_id_evaluation_jobs",
        "human_review_tasks",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_human_review_tasks_created_by_api_keys",
        "human_review_tasks",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_human_review_tasks_run_id_tenant_id_evaluation_runs",
        "human_review_tasks",
        "evaluation_runs",
        ["run_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_human_review_tasks_job_id_run_id_evaluation_jobs",
        "human_review_tasks",
        "evaluation_jobs",
        ["job_id", "run_id"],
        ["id", "run_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_human_review_tasks_created_by_tenant_id_api_keys",
        "human_review_tasks",
        "api_keys",
        ["created_by", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        "fk_human_review_submissions_task_id_human_review_tasks",
        "human_review_submissions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_human_review_submissions_reviewer_id_api_keys",
        "human_review_submissions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_human_review_submissions_task_tenant",
        "human_review_submissions",
        "human_review_tasks",
        ["task_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_human_review_submissions_reviewer_tenant",
        "human_review_submissions",
        "api_keys",
        ["reviewer_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        "fk_human_review_adjudications_task_id_human_review_tasks",
        "human_review_adjudications",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_human_review_adjudications_adjudicator_id_api_keys",
        "human_review_adjudications",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_human_review_adjudications_task_tenant",
        "human_review_adjudications",
        "human_review_tasks",
        ["task_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_human_review_adjudications_adjudicator_tenant",
        "human_review_adjudications",
        "api_keys",
        ["adjudicator_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    for table_name, constraint_name in (
        (
            "artifact_references",
            "fk_artifact_references_run_id_tenant_id_evaluation_runs",
        ),
        (
            "dataset_versions",
            "fk_dataset_versions_dataset_id_tenant_id_datasets",
        ),
        (
            "dataset_versions",
            "fk_dataset_versions_artifact_id_tenant_id_artifact_references",
        ),
        (
            "evaluation_runs",
            "fk_evaluation_runs_dataset_version_tenant",
        ),
        (
            "evaluation_runs",
            "fk_evaluation_runs_created_by_tenant_id_api_keys",
        ),
        (
            "case_results",
            "fk_case_results_job_id_run_id_evaluation_jobs",
        ),
        (
            "human_review_tasks",
            "fk_human_review_tasks_run_id_tenant_id_evaluation_runs",
        ),
        (
            "human_review_tasks",
            "fk_human_review_tasks_job_id_run_id_evaluation_jobs",
        ),
        (
            "human_review_tasks",
            "fk_human_review_tasks_created_by_tenant_id_api_keys",
        ),
        (
            "human_review_submissions",
            "fk_human_review_submissions_task_tenant",
        ),
        (
            "human_review_submissions",
            "fk_human_review_submissions_reviewer_tenant",
        ),
        (
            "human_review_adjudications",
            "fk_human_review_adjudications_task_tenant",
        ),
        (
            "human_review_adjudications",
            "fk_human_review_adjudications_adjudicator_tenant",
        ),
    ):
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")

    op.create_foreign_key(
        "fk_artifact_references_run_id_evaluation_runs",
        "artifact_references",
        "evaluation_runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_dataset_versions_dataset_id_datasets",
        "dataset_versions",
        "datasets",
        ["dataset_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_dataset_versions_artifact_id_artifact_references",
        "dataset_versions",
        "artifact_references",
        ["artifact_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_evaluation_runs_dataset_version_id_dataset_versions",
        "evaluation_runs",
        "dataset_versions",
        ["dataset_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_evaluation_runs_created_by_api_keys",
        "evaluation_runs",
        "api_keys",
        ["created_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_case_results_job_id_evaluation_jobs",
        "case_results",
        "evaluation_jobs",
        ["job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_case_results_run_id_evaluation_runs",
        "case_results",
        "evaluation_runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_human_review_tasks_run_id_evaluation_runs",
        "human_review_tasks",
        "evaluation_runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_human_review_tasks_job_id_evaluation_jobs",
        "human_review_tasks",
        "evaluation_jobs",
        ["job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_human_review_tasks_created_by_api_keys",
        "human_review_tasks",
        "api_keys",
        ["created_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_human_review_submissions_task_id_human_review_tasks",
        "human_review_submissions",
        "human_review_tasks",
        ["task_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_human_review_submissions_reviewer_id_api_keys",
        "human_review_submissions",
        "api_keys",
        ["reviewer_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_human_review_adjudications_task_id_human_review_tasks",
        "human_review_adjudications",
        "human_review_tasks",
        ["task_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_human_review_adjudications_adjudicator_id_api_keys",
        "human_review_adjudications",
        "api_keys",
        ["adjudicator_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    for table_name, constraint_name in (
        (
            "human_review_tasks",
            "uq_human_review_tasks_id_tenant_id",
        ),
        ("evaluation_jobs", "uq_evaluation_jobs_id_run_id"),
        ("evaluation_runs", "uq_evaluation_runs_id_tenant_id"),
        ("dataset_versions", "uq_dataset_versions_id_tenant_id"),
        (
            "artifact_references",
            "uq_artifact_references_id_tenant_id",
        ),
        ("datasets", "uq_datasets_id_tenant_id"),
        ("api_keys", "uq_api_keys_id_tenant_id"),
    ):
        op.drop_constraint(constraint_name, table_name, type_="unique")

    op.drop_column("dataset_versions", "tenant_id")
