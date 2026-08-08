from pathlib import Path

import yaml

WORKFLOW_PATH = Path(".github/workflows/release-candidate-evidence.yml")


def test_release_candidate_workflow_uses_v2_capacity_concurrency_group() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))

    assert workflow["concurrency"]["group"] == "release-candidate-fair-capacity-v2"


def test_release_candidate_workflow_stages_large_queue_after_initial_gate() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["fair-capacity"]["steps"]
    named_steps = {step["name"]: step for step in steps if "name" in step}

    start = named_steps["Start PostgreSQL and Redis with Compose"]["run"]
    assert "deploy/compose.yaml" in start
    assert "postgres redis" in start
    assert "--wait" in start
    assert "alembic upgrade head" in named_steps["Apply migrations"]["run"]

    initial = named_steps["Execute and verify 1k and 10k queues"]["run"]
    large = named_steps["Execute and verify 100k queue after initial gate"]["run"]
    assert "python -m scripts.run_fair_capacity_test" in initial
    assert '--queue-sizes "1000,10000"' in initial
    assert "--stage initial" in initial
    assert "--sample-jobs 100" in initial
    assert '--source-commit "$GITHUB_SHA"' in initial
    assert '--queue-sizes "100000"' in large
    assert "--stage large" in large
    assert "--sample-jobs 100" in large
    assert '--prior-assessment "$RC_EXECUTION_ROOT/initial/assessment.json"' in large
    assert steps.index(named_steps["Execute and verify 1k and 10k queues"]) < steps.index(
        named_steps["Execute and verify 100k queue after initial gate"]
    )


def test_release_candidate_workflow_preserves_partial_evidence() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["fair-capacity"]["steps"]
    named_steps = {step["name"]: step for step in steps if "name" in step}

    upload = named_steps["Upload evidence even when execution fails"]
    commit = named_steps["Commit immutable evidence to the target branch"]
    diagnostics = named_steps["Preserve runner and Compose diagnostics"]
    assert "always()" in upload["if"]
    assert "always()" in commit["if"]
    assert "always()" in diagnostics["if"]
    assert upload["with"]["if-no-files-found"] == "error"
    assert 'git push origin "HEAD:codex/evidence-gate-1"' in commit["run"]
