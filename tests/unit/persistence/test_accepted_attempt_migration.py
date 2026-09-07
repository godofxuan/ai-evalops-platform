from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command


def test_accepted_attempt_binding_is_nullable_without_inventing_historical_identity(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL", "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops"
    )
    config = Config(Path(__file__).resolve().parents[3] / "alembic.ini")
    command.upgrade(config, "20260907_0029:20260907_0030", sql=True)
    sql = capsys.readouterr().out
    assert "ADD COLUMN accepted_attempt_id UUID" in sql
    assert "FOREIGN KEY(accepted_attempt_id, job_id) REFERENCES job_attempts (id, job_id)" in sql
    assert "UNIQUE (id, job_id)" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "UPDATE case_results" not in sql and "SET NOT NULL" not in sql
    command.downgrade(config, "20260907_0030:20260907_0029", sql=True)
    sql = capsys.readouterr().out
    assert "DROP COLUMN accepted_attempt_id" in sql
    assert "DROP TABLE" not in sql
