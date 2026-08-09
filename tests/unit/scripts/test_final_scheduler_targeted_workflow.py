from pathlib import Path

import yaml

WORKFLOW_PATH = Path(".github/workflows/final-scheduler-targeted.yml")


def test_targeted_workflow_is_manually_started_after_ci_qualification() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))

    triggers = workflow[True]
    assert triggers["workflow_dispatch"] is None
    assert triggers["push"] == {
        "branches": ["codex/evidence-gate-1"],
        "paths": [".github/final-scheduler-targeted-trigger.txt"],
    }
    assert workflow["concurrency"]["group"] == "final-scheduler-targeted-v1"
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_targeted_workflow_runs_four_frozen_repetitions_and_fails_closed() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["targeted"]["steps"]
    named_steps = {step["name"]: step for step in steps if "name" in step}

    execution = named_steps["Execute four targeted repetitions"]["run"]
    assert "for repetition in 1 2 3 4" in execution
    assert "python -m scripts.run_fair_capacity_test" in execution
    assert "--stage targeted" in execution
    assert '--queue-sizes "1000"' in execution
    assert "--sample-jobs 100" in execution
    assert '--source-commit "$GITHUB_SHA"' in execution

    assessment = named_steps["Assess repeated self-scaling gate and seal manifest"]
    assert "always()" in assessment["if"]
    assert "python -m scripts.targeted_scheduler_evidence" in assessment["run"]
    assert assessment["run"].count("--input-csv") == 4
    assert "--manifest-root" in assessment["run"]

    upload = named_steps["Upload immutable targeted evidence"]
    commit = named_steps["Commit immutable targeted evidence"]
    assert "always()" in upload["if"]
    assert "always()" in commit["if"]
    assert upload["with"]["retention-days"] == 90
    assert 'git push origin "HEAD:codex/evidence-gate-1"' in commit["run"]
