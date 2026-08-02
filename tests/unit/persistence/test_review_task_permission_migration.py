from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_offline_upgrade_adds_default_denied_review_task_creator_permission(
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
    assert (
        "ALTER TABLE api_keys ADD COLUMN can_create_review_tasks BOOLEAN DEFAULT false NOT NULL"
    ) in sql


def test_offline_downgrade_removes_only_review_task_creator_permission(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    config = Config(PROJECT_ROOT / "alembic.ini")

    command.downgrade(config, "20260802_0011:20260802_0010", sql=True)

    sql = capsys.readouterr().out
    assert "ALTER TABLE api_keys DROP COLUMN can_create_review_tasks" in sql
    assert "DROP TABLE" not in sql
