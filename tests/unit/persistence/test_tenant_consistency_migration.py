from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_offline_upgrade_adds_guarded_cross_table_tenant_constraints(
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
    assert "ALTER TABLE dataset_versions ADD COLUMN tenant_id UUID" in sql
    assert "dataset/artifact tenant mismatch" in sql
    assert "run/dataset-version tenant mismatch" in sql
    assert "review submission/reviewer tenant mismatch" in sql
    assert "UPDATE dataset_versions" in sql
    assert "SET tenant_id = datasets.tenant_id" in sql
    assert "ALTER COLUMN tenant_id SET NOT NULL" in sql
    for constraint_name in (
        "uq_api_keys_id_tenant_id",
        "uq_dataset_versions_id_tenant_id",
        "fk_artifact_references_run_id_tenant_id_evaluation_runs",
        "fk_dataset_versions_artifact_id_tenant_id_artifact_references",
        "fk_evaluation_runs_created_by_tenant_id_api_keys",
        "fk_case_results_job_id_run_id_evaluation_jobs",
        "fk_human_review_tasks_job_id_run_id_evaluation_jobs",
        "fk_human_review_submissions_reviewer_tenant",
        "fk_human_review_adjudications_adjudicator_tenant",
    ):
        assert constraint_name in sql


def test_offline_downgrade_restores_previous_single_parent_constraints(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "EVALOPS_DATABASE_URL",
        "postgresql+psycopg://evalops:evalops@127.0.0.1:5432/evalops",
    )
    config = Config(PROJECT_ROOT / "alembic.ini")

    command.downgrade(config, "20260802_0010:20260802_0009", sql=True)

    sql = capsys.readouterr().out
    for previous_constraint_name in (
        "fk_artifact_references_run_id_evaluation_runs",
        "fk_dataset_versions_dataset_id_datasets",
        "fk_dataset_versions_artifact_id_artifact_references",
        "fk_evaluation_runs_dataset_version_id_dataset_versions",
        "fk_evaluation_runs_created_by_api_keys",
        "fk_case_results_job_id_evaluation_jobs",
        "fk_case_results_run_id_evaluation_runs",
        "fk_human_review_tasks_run_id_evaluation_runs",
        "fk_human_review_tasks_job_id_evaluation_jobs",
        "fk_human_review_tasks_created_by_api_keys",
        "fk_human_review_submissions_task_id_human_review_tasks",
        "fk_human_review_submissions_reviewer_id_api_keys",
        "fk_human_review_adjudications_task_id_human_review_tasks",
        "fk_human_review_adjudications_adjudicator_id_api_keys",
    ):
        assert previous_constraint_name in sql
    for p2_unique_name in (
        "uq_api_keys_id_tenant_id",
        "uq_datasets_id_tenant_id",
        "uq_artifact_references_id_tenant_id",
        "uq_dataset_versions_id_tenant_id",
        "uq_evaluation_runs_id_tenant_id",
        "uq_evaluation_jobs_id_run_id",
        "uq_human_review_tasks_id_tenant_id",
    ):
        assert f"DROP CONSTRAINT {p2_unique_name}" in sql
    assert "ALTER TABLE dataset_versions DROP COLUMN tenant_id" in sql
