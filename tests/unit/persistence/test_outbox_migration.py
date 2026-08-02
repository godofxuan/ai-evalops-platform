from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_offline_upgrade_creates_tenant_scoped_progress_event_outbox(
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
    assert "CREATE TABLE progress_event_outbox" in sql
    assert "FOREIGN KEY(run_id, tenant_id)" in sql
    assert "REFERENCES evaluation_runs (id, tenant_id) ON DELETE CASCADE" in sql
    assert "CHECK (attempt_count >= 0)" in sql
    assert "WHERE published_at IS NULL" in sql


def test_offline_downgrade_removes_only_progress_event_outbox(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    config = Config(PROJECT_ROOT / "alembic.ini")

    command.downgrade(config, "20260802_0013:20260802_0012", sql=True)

    sql = capsys.readouterr().out
    assert "DROP TABLE progress_event_outbox" in sql
    assert "DROP COLUMN origin_traceparent" not in sql


def test_offline_upgrade_adds_partial_outbox_retention_index(
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
    assert "CREATE INDEX ix_progress_event_outbox_published_retention" in sql
    assert "ON progress_event_outbox (published_at, id)" in sql
    assert "WHERE published_at IS NOT NULL" in sql


def test_offline_retention_downgrade_drops_only_published_index(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    config = Config(PROJECT_ROOT / "alembic.ini")

    command.downgrade(config, "20260803_0014:20260802_0013", sql=True)

    sql = capsys.readouterr().out
    assert "DROP INDEX ix_progress_event_outbox_published_retention" in sql
    assert "DROP TABLE progress_event_outbox" not in sql
    assert "DROP COLUMN" not in sql
