from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_agent_execution_artifact_upgrade_preserves_artifact_store_boundary_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    config = Config(PROJECT_ROOT / "alembic.ini")

    command.upgrade(config, "20260810_0018:20260819_0019", sql=True)

    sql = capsys.readouterr().out
    assert "DROP CONSTRAINT ck_artifact_references_artifact_type" in sql
    assert "ck_artifact_references_ck_artifact_references_artifact_type" not in sql
    assert "CREATE TABLE agent_execution_artifacts" in sql
    assert "artifact_reference_id UUID NOT NULL" in sql
    assert "content_sha256 VARCHAR(64) NOT NULL" in sql
    assert "uq_agent_execution_artifacts_content_identity" in sql
    assert "agent_execution" in sql
