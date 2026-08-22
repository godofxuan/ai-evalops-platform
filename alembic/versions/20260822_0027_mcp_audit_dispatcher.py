"""Add leased background delivery and dead letters to the MCP audit outbox."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_0027"
down_revision: str | None = "20260822_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mcp_audit_outbox", sa.Column("actor_id", sa.String(128), nullable=True))
    op.add_column(
        "mcp_audit_outbox",
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.add_column("mcp_audit_outbox", sa.Column("lease_owner", sa.String(128)))
    op.add_column("mcp_audit_outbox", sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
    op.add_column(
        "mcp_audit_outbox",
        sa.Column("lease_version", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "mcp_audit_outbox",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8"),
    )
    op.add_column("mcp_audit_outbox", sa.Column("dead_lettered_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE mcp_audit_outbox SET actor_id = api_key_id::text")
    op.alter_column("mcp_audit_outbox", "actor_id", nullable=False)
    op.alter_column("mcp_audit_outbox", "available_at", nullable=False)

    op.drop_constraint(
        "ck_mcp_audit_outbox_delivery_status_known",
        "mcp_audit_outbox",
        type_="check",
    )
    op.create_check_constraint(
        "ck_mcp_audit_outbox_delivery_status_known",
        "mcp_audit_outbox",
        "delivery_status IN ('PENDING', 'DELIVERED', 'DEAD_LETTER')",
    )
    op.create_check_constraint(
        "ck_mcp_audit_outbox_lease_version_nonnegative",
        "mcp_audit_outbox",
        "lease_version >= 0",
    )
    op.create_check_constraint(
        "ck_mcp_audit_outbox_max_attempts_positive",
        "mcp_audit_outbox",
        "max_attempts > 0",
    )
    op.create_check_constraint(
        "ck_mcp_audit_outbox_lease_fields_consistent",
        "mcp_audit_outbox",
        "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_mcp_audit_outbox_terminal_delivery_not_leased",
        "mcp_audit_outbox",
        "delivery_status = 'PENDING' OR (lease_owner IS NULL AND lease_expires_at IS NULL)",
    )
    op.drop_index("ix_mcp_audit_outbox_pending", table_name="mcp_audit_outbox")
    op.create_index(
        "ix_mcp_audit_outbox_pending",
        "mcp_audit_outbox",
        ["available_at", "created_at", "id"],
        postgresql_where=sa.text("delivery_status = 'PENDING'"),
    )


def downgrade() -> None:
    op.execute(
        "UPDATE mcp_audit_outbox SET delivery_status = 'PENDING', "
        "dead_lettered_at = NULL WHERE delivery_status = 'DEAD_LETTER'"
    )
    op.drop_index("ix_mcp_audit_outbox_pending", table_name="mcp_audit_outbox")
    op.create_index(
        "ix_mcp_audit_outbox_pending",
        "mcp_audit_outbox",
        ["delivery_status", "created_at"],
    )
    for constraint in (
        "ck_mcp_audit_outbox_terminal_delivery_not_leased",
        "ck_mcp_audit_outbox_lease_fields_consistent",
        "ck_mcp_audit_outbox_max_attempts_positive",
        "ck_mcp_audit_outbox_lease_version_nonnegative",
        "ck_mcp_audit_outbox_delivery_status_known",
    ):
        op.drop_constraint(constraint, "mcp_audit_outbox", type_="check")
    op.create_check_constraint(
        "ck_mcp_audit_outbox_delivery_status_known",
        "mcp_audit_outbox",
        "delivery_status IN ('PENDING', 'DELIVERED')",
    )
    for column in (
        "dead_lettered_at",
        "max_attempts",
        "lease_version",
        "lease_expires_at",
        "lease_owner",
        "available_at",
        "actor_id",
    ):
        op.drop_column("mcp_audit_outbox", column)
