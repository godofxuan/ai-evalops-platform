from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command


def test_experiment_admission_migration_preserves_unmanaged_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL", "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops"
    )
    config = Config(Path(__file__).resolve().parents[3] / "alembic.ini")
    command.upgrade(config, "20260907_0030:20260907_0031", sql=True)
    sql = capsys.readouterr().out
    assert "ADD COLUMN product_experiment_id UUID" in sql
    assert "ADD COLUMN max_active_jobs INTEGER" in sql
    assert "FOREIGN KEY(product_experiment_id, tenant_id)" in sql
    assert "REFERENCES product_experiments (id, tenant_id) DEFERRABLE INITIALLY DEFERRED" in sql
    assert "UPDATE evaluation_runs" not in sql
    assert "UPDATE product_experiments" not in sql
    command.downgrade(config, "20260907_0031:20260907_0030", sql=True)
    sql = capsys.readouterr().out
    assert "DROP COLUMN product_experiment_id" in sql
    assert "DROP COLUMN max_active_jobs" in sql
