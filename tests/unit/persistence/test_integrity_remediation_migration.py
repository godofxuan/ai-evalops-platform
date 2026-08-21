from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _config(monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    return Config(PROJECT_ROOT / "alembic.ini")


def test_integrity_remediation_upgrade_contains_state_trigger_sequence_and_outbox(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(_config(monkeypatch), "head", sql=True)
    sql = capsys.readouterr().out
    assert "ADD COLUMN lifecycle_status" in sql
    assert "ADD COLUMN deletion_token" in sql
    assert "enforce_artifact_blob_active_reference" in sql
    assert "CREATE TABLE mcp_audit_outbox" in sql
    assert "uq_mcp_audit_outbox_call_identity" in sql
    assert "CREATE SEQUENCE scheduler_claim_receipt_seq" in sql
    assert "setval('scheduler_claim_receipt_seq'" in sql


def test_integrity_remediation_downgrade_removes_all_new_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.downgrade(
        _config(monkeypatch),
        "20260822_0026:20260820_0025",
        sql=True,
    )
    sql = capsys.readouterr().out
    assert "DROP SEQUENCE scheduler_claim_receipt_seq" in sql
    assert "DROP TABLE mcp_audit_outbox" in sql
    assert "DROP FUNCTION enforce_artifact_blob_active_reference" in sql
    assert "DROP COLUMN lifecycle_status" in sql
    assert "DROP COLUMN deletion_token" in sql
