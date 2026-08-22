from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _config(monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    return Config(PROJECT_ROOT / "alembic.ini")


def test_audit_dispatcher_upgrade_adds_leases_dead_letters_and_due_index(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(_config(monkeypatch), "20260822_0026:20260822_0027", sql=True)
    sql = capsys.readouterr().out

    assert "ADD COLUMN actor_id" in sql
    assert "ADD COLUMN available_at" in sql
    assert "ADD COLUMN lease_owner" in sql
    assert "ADD COLUMN lease_expires_at" in sql
    assert "ADD COLUMN lease_version" in sql
    assert "ADD COLUMN max_attempts" in sql
    assert "ADD COLUMN dead_lettered_at" in sql
    assert "DEAD_LETTER" in sql
    assert "delivery_status = 'PENDING'" in sql


def test_audit_dispatcher_downgrade_restores_original_status_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.downgrade(
        _config(monkeypatch),
        "20260822_0027:20260822_0026",
        sql=True,
    )
    sql = capsys.readouterr().out

    assert "SET delivery_status = 'PENDING'" in sql
    assert "DROP COLUMN dead_lettered_at" in sql
    assert "DROP COLUMN lease_version" in sql
    assert "DROP COLUMN actor_id" in sql
    assert "delivery_status IN ('PENDING', 'DELIVERED')" in sql
