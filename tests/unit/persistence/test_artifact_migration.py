from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_offline_upgrade_separates_artifact_blobs_and_references(
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
    assert "CREATE TABLE artifact_blobs" in sql
    assert "CREATE TABLE artifact_references" in sql
    assert "INSERT INTO artifact_blobs" in sql
    assert "INSERT INTO artifact_references" in sql
    assert "fk_dataset_versions_artifact_id_artifact_references" in sql
    assert "DROP TABLE artifacts" in sql


def test_offline_downgrade_is_guarded_against_lossy_owner_collapse(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    config = Config(PROJECT_ROOT / "alembic.ini")

    command.downgrade(config, "20260802_0009:20260729_0008", sql=True)

    sql = capsys.readouterr().out
    assert "artifact downgrade would lose distinct ownership references" in sql
    assert "CREATE TABLE artifacts" in sql
    assert "INSERT INTO artifacts" in sql
    assert "fk_dataset_versions_artifact_id_artifacts" in sql
    assert "DROP TABLE artifact_references" in sql
    assert "DROP TABLE artifact_blobs" in sql
