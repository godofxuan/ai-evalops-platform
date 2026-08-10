from importlib import import_module

import pytest


@pytest.mark.parametrize(
    "path",
    [
        "app/services/scheduler.py",
        "scripts/run_fair_capacity_test.py",
        "alembic/versions/0001_initial.py",
        "deploy/compose.yaml",
        "pyproject.toml",
        "uv.lock",
        "alembic.ini",
        ".python-version",
    ],
)
def test_behavioral_source_lock_rejects_execution_dependencies(path: str) -> None:
    module = import_module("scripts.behavioral_source_lock")

    assert module.behavioral_source_lock_violations([path]) == (path,)


@pytest.mark.parametrize(
    "path",
    [
        "docs/learning/evidence_gate_hardening/11_PASSIVE_MEASUREMENT_SYSTEM.md",
        "docs/results/release/v0.1.0/measurement-system-v2/report.json",
        ".github/measurement-system-v2-trigger.txt",
    ],
)
def test_behavioral_source_lock_allows_non_behavioral_evidence_paths(path: str) -> None:
    module = import_module("scripts.behavioral_source_lock")

    assert module.behavioral_source_lock_violations([path]) == ()


@pytest.mark.parametrize("path", ["../app/scheduler.py", "/app/scheduler.py", "app\\x.py"])
def test_behavioral_source_lock_fails_closed_for_non_repository_paths(path: str) -> None:
    module = import_module("scripts.behavioral_source_lock")

    assert module.behavioral_source_lock_violations([path]) == (path,)
