from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command


def test_experiment_source_reference_is_tenant_bound_and_not_backfilled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL", "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops"
    )
    config = Config(Path(__file__).resolve().parents[3] / "alembic.ini")
    command.upgrade(config, "20260907_0031:20260907_0032", sql=True)
    sql = capsys.readouterr().out
    assert "ADD COLUMN source_artifact_reference_id UUID" in sql
    assert "FOREIGN KEY(source_artifact_reference_id, tenant_id)" in sql
    assert "REFERENCES artifact_references (id, tenant_id) ON DELETE RESTRICT" in sql
    assert "UPDATE product_experiments" not in sql
    command.downgrade(config, "20260907_0032:20260907_0031", sql=True)
    assert "DROP COLUMN source_artifact_reference_id" in capsys.readouterr().out
