from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command


def test_execution_deadline_migration_is_nullable_and_does_not_backfill(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL", "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops"
    )
    config = Config(Path(__file__).resolve().parents[3] / "alembic.ini")
    command.upgrade(config, "20260907_0028:20260907_0029", sql=True)
    sql = capsys.readouterr().out
    assert "ADD COLUMN execution_deadline_at TIMESTAMP WITH TIME ZONE" in sql
    assert "UPDATE evaluation_runs" not in sql and "NOT NULL" not in sql
    command.downgrade(config, "20260907_0029:20260907_0028", sql=True)
    sql = capsys.readouterr().out
    assert "DROP COLUMN execution_deadline_at" in sql
    assert "DROP TABLE" not in sql
