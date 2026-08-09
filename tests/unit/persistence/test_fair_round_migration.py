from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_fair_round_upgrade_creates_bounded_scheduler_state_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    config = Config(PROJECT_ROOT / "alembic.ini")

    command.upgrade(config, "20260809_0017:20260810_0018", sql=True)

    sql = capsys.readouterr().out
    assert "CREATE TABLE scheduler_coordination" in sql
    assert "CREATE TABLE tenant_scheduler_states" in sql
    assert "FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE" in sql
    assert "UNIQUE (generation, tenant_id)" in sql
    assert "CREATE INDEX ix_tenant_scheduler_states_active_permits" in sql
    assert "INSERT INTO scheduler_coordination" in sql
    assert "ADD COLUMN scheduler_claim_sequence BIGINT" in sql
    assert "UNIQUE (scheduler_claim_sequence)" in sql


def test_fair_round_downgrade_removes_candidate3_state_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    config = Config(PROJECT_ROOT / "alembic.ini")

    command.downgrade(config, "20260810_0018:20260809_0017", sql=True)

    sql = capsys.readouterr().out
    assert "DROP TABLE tenant_scheduler_states" in sql
    assert "DROP TABLE scheduler_coordination" in sql
    assert "DROP COLUMN scheduler_claim_sequence" in sql
