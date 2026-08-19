"""Bind human review tasks to immutable source and packet identities."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260820_0022"
down_revision: str | None = "20260820_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("human_review_tasks", sa.Column("source_type", sa.String(32)))
    op.add_column("human_review_tasks", sa.Column("source_record_id", sa.Uuid()))
    op.add_column("human_review_tasks", sa.Column("source_content_sha256", sa.String(64)))
    op.add_column("human_review_tasks", sa.Column("packet_schema_version", sa.String(64)))
    op.add_column("human_review_tasks", sa.Column("artifact_id", sa.Uuid()))
    op.add_column("human_review_tasks", sa.Column("artifact_sha256", sa.String(64)))
    op.add_column("human_review_tasks", sa.Column("packet_sha256", sa.String(64)))
    op.add_column("human_review_tasks", sa.Column("evaluator_visibility_policy", sa.String(64)))
    op.add_column(
        "human_review_tasks",
        sa.Column(
            "evaluator_evidence_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION pg_temp.evalops_canonical_jsonb(value jsonb)
            RETURNS text
            LANGUAGE sql
            IMMUTABLE
            AS $$
                SELECT CASE jsonb_typeof(value)
                    WHEN 'object' THEN '{' || COALESCE((
                        SELECT string_agg(
                            to_jsonb(entry.key)::text || ':' ||
                            pg_temp.evalops_canonical_jsonb(entry.value),
                            ',' ORDER BY entry.key
                        ) FROM jsonb_each(value) AS entry
                    ), '') || '}'
                    WHEN 'array' THEN '[' || COALESCE((
                        SELECT string_agg(
                            pg_temp.evalops_canonical_jsonb(entry.value),
                            ',' ORDER BY entry.ordinality
                        ) FROM jsonb_array_elements(value)
                            WITH ORDINALITY AS entry(value, ordinality)
                    ), '') || ']'
                    ELSE value::text
                END
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE human_review_tasks AS task
            SET source_type = 'case_result',
                source_record_id = COALESCE(result.id, task.id),
                source_content_sha256 = encode(sha256(convert_to(
                    pg_temp.evalops_canonical_jsonb(task.packet_json), 'UTF8'
                )), 'hex'),
                packet_schema_version = 'review-packet/legacy-v0',
                packet_sha256 = encode(sha256(convert_to(
                    pg_temp.evalops_canonical_jsonb(task.packet_json), 'UTF8'
                )), 'hex'),
                evaluator_visibility_policy = 'after-submission-or-adjudication'
            FROM case_results AS result
            WHERE result.job_id = task.job_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE human_review_tasks AS task
            SET source_type = 'case_result',
                source_record_id = task.id,
                source_content_sha256 = encode(sha256(convert_to(
                    pg_temp.evalops_canonical_jsonb(task.packet_json), 'UTF8'
                )), 'hex'),
                packet_schema_version = 'review-packet/legacy-v0',
                packet_sha256 = encode(sha256(convert_to(
                    pg_temp.evalops_canonical_jsonb(task.packet_json), 'UTF8'
                )), 'hex'),
                evaluator_visibility_policy = 'after-submission-or-adjudication'
            WHERE task.source_type IS NULL
            """
        )
    )

    for column in (
        "source_type",
        "source_record_id",
        "source_content_sha256",
        "packet_schema_version",
        "packet_sha256",
        "evaluator_visibility_policy",
    ):
        op.alter_column("human_review_tasks", column, nullable=False)
    op.drop_constraint("uq_human_review_tasks_run_id_case_id", "human_review_tasks", type_="unique")
    op.create_unique_constraint(
        "uq_human_review_tasks_source_identity",
        "human_review_tasks",
        ["tenant_id", "source_type", "source_record_id", "packet_schema_version"],
    )
    op.create_check_constraint(
        "human_review_tasks_source_type",
        "human_review_tasks",
        "source_type IN ('case_result', 'agent_artifact')",
    )
    op.create_check_constraint(
        "human_review_tasks_source_binding",
        "human_review_tasks",
        "(source_type = 'agent_artifact' AND artifact_id = source_record_id "
        "AND artifact_sha256 IS NOT NULL) OR "
        "(source_type = 'case_result' AND artifact_id IS NULL AND artifact_sha256 IS NULL)",
    )
    op.create_foreign_key(
        "fk_human_review_tasks_agent_artifact",
        "human_review_tasks",
        "agent_execution_artifacts",
        ["artifact_id", "tenant_id", "run_id"],
        ["id", "tenant_id", "run_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_human_review_tasks_agent_artifact", "human_review_tasks", type_="foreignkey"
    )
    op.drop_constraint("human_review_tasks_source_binding", "human_review_tasks", type_="check")
    op.drop_constraint("human_review_tasks_source_type", "human_review_tasks", type_="check")
    op.drop_constraint(
        "uq_human_review_tasks_source_identity", "human_review_tasks", type_="unique"
    )
    op.create_unique_constraint(
        "uq_human_review_tasks_run_id_case_id",
        "human_review_tasks",
        ["run_id", "case_id"],
    )
    for column in (
        "evaluator_evidence_json",
        "evaluator_visibility_policy",
        "packet_sha256",
        "artifact_sha256",
        "artifact_id",
        "packet_schema_version",
        "source_content_sha256",
        "source_record_id",
        "source_type",
    ):
        op.drop_column("human_review_tasks", column)
