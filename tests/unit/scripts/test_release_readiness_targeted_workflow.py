from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

WORKFLOW_PATH = Path(".github/workflows/release-readiness-targeted.yml")


def _workflow() -> dict[Any, Any]:
    return cast(dict[Any, Any], yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8")))


def test_workflow_is_branch_scoped_and_cannot_modify_repository() -> None:
    workflow = _workflow()

    assert workflow[True]["push"] == {
        "branches": ["codex/release-readiness-remediation-v1"],
        "paths": [".github/release-readiness-targeted-trigger.txt"],
    }
    assert workflow["permissions"] == {"contents": "read"}
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "git push" not in workflow_text
    assert "git commit" not in workflow_text


def test_workflow_runs_frozen_gate_and_preserves_failed_evidence() -> None:
    workflow = _workflow()
    steps = workflow["jobs"]["targeted"]["steps"]
    named_steps = {step["name"]: step for step in steps if "name" in step}

    execution = named_steps["Execute four preregistered repetitions"]["run"]
    assert "for repetition in 1 2 3 4" in execution
    assert "python -m scripts.run_fair_capacity_test" in execution
    assert "--stage targeted" in execution
    assert '--queue-sizes "1000"' in execution
    assert "--sample-jobs 100" in execution
    assert '--source-commit "$GITHUB_SHA"' in execution
    assert "--performance-attribution" not in execution

    assessment = named_steps["Assess frozen 4-to-8 worker gate"]
    assert assessment["continue-on-error"] is True
    assert assessment["run"].count("--input-csv") == 4

    upload = named_steps["Upload immutable targeted evidence"]
    assert "always()" in upload["if"]
    assert upload["with"]["retention-days"] == 90
    assert upload["with"]["path"] == "${{ env.TARGETED_EXECUTION_ROOT }}"

    enforcement = named_steps["Enforce assessment result after evidence upload"]
    assert "always()" in enforcement["if"]
    assert "steps.assess.outcome" in enforcement["run"]


def test_workflow_runs_database_concurrency_regressions() -> None:
    workflow = _workflow()
    steps = workflow["jobs"]["targeted"]["steps"]
    named_steps = {step["name"]: step for step in steps if "name" in step}
    command = named_steps["Run scheduler concurrency regressions"]["run"]

    assert "tests/unit/jobs/test_claim_fast_path.py" in command
    assert "tests/concurrency/test_tenant_durable_fairness.py" in command
    assert "tests/concurrency/test_tenant_claim_parallelism.py" in command
    assert "tests/concurrency/test_tenant_fair_claiming.py" in command
    assert "tests/concurrency/test_job_claiming.py" in command
