from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import CheckConstraint, ForeignKeyConstraint

from alembic import command
from app.domain.enums import ArtifactType
from app.persistence.orm_models import ProductExperiment


def test_published_report_binds_tenant_baseline_run_and_exact_blob() -> None:
    assert ArtifactType.PRODUCT_EXPERIMENT_REPORT.value == "product_experiment_report"
    table = ProductExperiment.__table__
    for name in ("report_artifact_reference_id", "report_sha256", "report_snapshot_sha256"):
        assert table.c[name].nullable
    bindings = {
        (
            tuple(element.parent.name for element in constraint.elements),
            tuple(element.target_fullname for element in constraint.elements),
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert (
        ("report_artifact_reference_id", "tenant_id", "baseline_run_id", "report_sha256"),
        (
            "artifact_references.id",
            "artifact_references.tenant_id",
            "artifact_references.run_id",
            "artifact_references.blob_sha256",
        ),
    ) in bindings
    assert any(
        "report_snapshot_sha256 IS NOT NULL" in str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    )


def test_report_publication_migration_preserves_evidence_on_downgrade(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL", "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops"
    )
    config = Config(Path(__file__).resolve().parents[3] / "alembic.ini")
    command.upgrade(config, "20260907_0032:20260907_0033", sql=True)
    sql = capsys.readouterr().out
    assert "fk_product_experiments_report_identity" in sql
    assert "product_experiment_report" in sql
    assert "report_snapshot_sha256 IS NOT NULL" in sql
    assert "ck_artifact_references_ck_artifact_references" not in sql
    command.downgrade(config, "20260907_0033:20260907_0032", sql=True)
    downgrade = capsys.readouterr().out
    assert "DELETE FROM" not in downgrade.upper()
    assert downgrade.index("ADD CONSTRAINT ck_artifact_references_artifact_type") < downgrade.index(
        "DROP COLUMN report_snapshot_sha256"
    )
