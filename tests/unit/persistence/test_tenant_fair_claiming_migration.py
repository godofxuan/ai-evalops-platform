from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_tenant_fair_claiming_upgrade_renders_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    config = Config(PROJECT_ROOT / "alembic.ini")

    command.upgrade(config, "20260808_0015:20260808_0016", sql=True)

    sql = capsys.readouterr().out
    assert "ADD COLUMN last_job_claimed_at TIMESTAMP WITH TIME ZONE" in sql
    assert "CREATE INDEX ix_tenants_last_job_claimed_at" in sql


def test_tenant_fair_claiming_downgrade_renders_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    config = Config(PROJECT_ROOT / "alembic.ini")

    command.downgrade(config, "20260808_0016:20260808_0015", sql=True)

    sql = capsys.readouterr().out
    assert "DROP INDEX ix_tenants_last_job_claimed_at" in sql
    assert "DROP COLUMN last_job_claimed_at" in sql
