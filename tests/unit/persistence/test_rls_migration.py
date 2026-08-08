from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RLS_TABLES = ("datasets", "dataset_versions", "evaluation_runs", "case_results")


def test_offline_upgrade_adds_direct_tenant_rls_policies(
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
    assert "ALTER TABLE case_results ADD COLUMN tenant_id UUID" in sql
    assert "UPDATE case_results" in sql
    assert "SET tenant_id = evaluation_runs.tenant_id" in sql
    assert "ALTER COLUMN tenant_id SET NOT NULL" in sql
    assert "fk_case_results_run_id_tenant_id_evaluation_runs" in sql
    assert "ix_case_results_tenant_id_run_id" in sql
    assert "current_setting('app.current_tenant_id', true)" in sql
    for table in RLS_TABLES:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql
        assert f"CREATE POLICY {table}_tenant_isolation ON {table}" in sql
    assert "FORCE ROW LEVEL SECURITY" not in sql
    assert "EXISTS (SELECT" not in sql


def test_offline_downgrade_removes_rls_before_tenant_column(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    config = Config(PROJECT_ROOT / "alembic.ini")

    command.downgrade(config, "20260808_0015:20260803_0014", sql=True)

    sql = capsys.readouterr().out
    for table in RLS_TABLES:
        assert f"DROP POLICY {table}_tenant_isolation ON {table}" in sql
        assert f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY" in sql
    assert "ALTER TABLE case_results DROP COLUMN tenant_id" in sql
