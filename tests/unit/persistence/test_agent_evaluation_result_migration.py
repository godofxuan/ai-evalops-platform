from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_agent_evaluation_result_upgrade_encodes_reproducible_identity_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    config = Config(PROJECT_ROOT / "alembic.ini")

    command.upgrade(config, "20260819_0019:20260819_0020", sql=True)

    sql = capsys.readouterr().out
    assert "CREATE TABLE agent_evaluation_results" in sql
    assert "fk_agent_eval_result_artifact_tenant_run" in sql
    assert "uq_agent_eval_results_identity" in sql
    assert "config_sha256 VARCHAR(64) NOT NULL" in sql
    assert "failure_taxonomy_json JSONB NOT NULL" in sql
