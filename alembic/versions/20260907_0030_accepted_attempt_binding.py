"""Bind new accepted results to their actual attempt without backfilling old evidence."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260907_0030"
down_revision: str | None = "20260907_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_job_attempts_id_job_id", "job_attempts", ["id", "job_id"])
    op.add_column("case_results", sa.Column("accepted_attempt_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_case_results_accepted_attempt_job",
        "case_results",
        "job_attempts",
        ["accepted_attempt_id", "job_id"],
        ["id", "job_id"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint("fk_case_results_accepted_attempt_job", "case_results", type_="foreignkey")
    op.drop_column("case_results", "accepted_attempt_id")
    op.drop_constraint("uq_job_attempts_id_job_id", "job_attempts", type_="unique")
