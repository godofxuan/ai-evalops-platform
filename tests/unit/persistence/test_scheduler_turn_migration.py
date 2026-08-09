from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_scheduler_turn_upgrade_renames_state_and_index_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    config = Config(PROJECT_ROOT / "alembic.ini")

    command.upgrade(config, "20260808_0016:20260809_0017", sql=True)

    sql = capsys.readouterr().out
    assert "DROP INDEX ix_tenants_last_job_claimed_at" in sql
    assert "RENAME last_job_claimed_at TO last_scheduler_turn_at" in sql
    assert "CREATE INDEX ix_tenants_last_scheduler_turn_at" in sql


def test_scheduler_turn_downgrade_restores_prior_state_name_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    config = Config(PROJECT_ROOT / "alembic.ini")

    command.downgrade(config, "20260809_0017:20260808_0016", sql=True)

    sql = capsys.readouterr().out
    assert "DROP INDEX ix_tenants_last_scheduler_turn_at" in sql
    assert "RENAME last_scheduler_turn_at TO last_job_claimed_at" in sql
    assert "CREATE INDEX ix_tenants_last_job_claimed_at" in sql
