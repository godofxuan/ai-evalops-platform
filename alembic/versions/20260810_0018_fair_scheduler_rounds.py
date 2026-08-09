"""Add bounded durable fair-round scheduler coordination."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_0018"
down_revision: str | None = "20260809_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduler_coordination",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "active_generation",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("active_priority", sa.Integer(), nullable=True),
        sa.Column(
            "durable_claim_sequence",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
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
        sa.CheckConstraint("id = 1", name="ck_scheduler_coordination_singleton_id"),
        sa.CheckConstraint(
            "active_generation >= 0",
            name="ck_scheduler_coordination_active_generation_nonnegative",
        ),
        sa.CheckConstraint(
            "durable_claim_sequence >= 0",
            name="ck_scheduler_coordination_claim_sequence_nonnegative",
        ),
        sa.CheckConstraint("version > 0", name="ck_scheduler_coordination_version_positive"),
        sa.PrimaryKeyConstraint("id", name="pk_scheduler_coordination"),
    )
    coordination = sa.table(
        "scheduler_coordination",
        sa.column("id", sa.Integer()),
        sa.column("active_generation", sa.BigInteger()),
        sa.column("active_priority", sa.Integer()),
        sa.column("durable_claim_sequence", sa.BigInteger()),
        sa.column("version", sa.Integer()),
    )
    op.bulk_insert(
        coordination,
        [
            {
                "id": 1,
                "active_generation": 0,
                "active_priority": None,
                "durable_claim_sequence": 0,
                "version": 1,
            }
        ],
    )

    op.create_table(
        "tenant_scheduler_states",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("round_priority", sa.Integer(), nullable=False),
        sa.Column("permit_order", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
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
            "generation > 0",
            name="ck_tenant_scheduler_states_generation_positive",
        ),
        sa.CheckConstraint(
            "permit_order > 0",
            name="ck_tenant_scheduler_states_permit_order_positive",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'consumed', 'empty')",
            name="ck_tenant_scheduler_states_status_known",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_tenant_scheduler_states_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_scheduler_states_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_tenant_scheduler_states"),
        sa.UniqueConstraint(
            "generation",
            "tenant_id",
            name="uq_tenant_scheduler_states_generation_tenant_id",
        ),
    )
    op.create_index(
        "ix_tenant_scheduler_states_active_permits",
        "tenant_scheduler_states",
        ["generation", "status", "permit_order"],
    )

    op.add_column(
        "job_attempts",
        sa.Column("scheduler_claim_sequence", sa.BigInteger(), nullable=True),
    )
    op.create_check_constraint(
        "ck_job_attempts_scheduler_claim_sequence_positive",
        "job_attempts",
        "scheduler_claim_sequence IS NULL OR scheduler_claim_sequence > 0",
    )
    op.create_unique_constraint(
        "uq_job_attempts_scheduler_claim_sequence",
        "job_attempts",
        ["scheduler_claim_sequence"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_job_attempts_scheduler_claim_sequence",
        "job_attempts",
        type_="unique",
    )
    op.drop_constraint(
        "ck_job_attempts_scheduler_claim_sequence_positive",
        "job_attempts",
        type_="check",
    )
    op.drop_column("job_attempts", "scheduler_claim_sequence")
    op.drop_index(
        "ix_tenant_scheduler_states_active_permits",
        table_name="tenant_scheduler_states",
    )
    op.drop_table("tenant_scheduler_states")
    op.drop_table("scheduler_coordination")
