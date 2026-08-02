from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_offline_upgrade_adds_nullable_run_origin_traceparent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    config = Config(PROJECT_ROOT / "alembic.ini")

    command.upgrade(config, "head", sql=True)

    sql = capsys.readouterr().out
    assert "ALTER TABLE evaluation_runs ADD COLUMN origin_traceparent VARCHAR(55)" in sql
    assert "UPDATE evaluation_runs" not in sql


def test_offline_downgrade_removes_only_run_origin_traceparent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    config = Config(PROJECT_ROOT / "alembic.ini")

    command.downgrade(config, "20260802_0012:20260802_0011", sql=True)

    sql = capsys.readouterr().out
    assert "ALTER TABLE evaluation_runs DROP COLUMN origin_traceparent" in sql
    assert "DROP TABLE" not in sql
