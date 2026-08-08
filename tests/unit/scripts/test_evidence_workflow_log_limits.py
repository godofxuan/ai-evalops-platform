from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize(
    "workflow_path,job_name",
    [
        (Path(".github/workflows/evidence-gate.yml"), "worker-scaling"),
        (Path(".github/workflows/fault-evidence.yml"), "fault-matrix"),
        (
            Path(".github/workflows/release-candidate-evidence.yml"),
            "fair-capacity",
        ),
    ],
)
def test_persisted_compose_diagnostics_have_a_git_safe_byte_limit(
    workflow_path: Path,
    job_name: str,
) -> None:
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["jobs"][job_name]["steps"]
    diagnostics = next(
        step for step in steps if step.get("name") == "Preserve runner and Compose diagnostics"
    )
    command = diagnostics["run"]

    assert "COMPOSE_LOG_LIMIT_BYTES=10485760" in command
    assert 'tail -c "$COMPOSE_LOG_LIMIT_BYTES"' in command
    assert "compose-log-policy.txt" in command
    assert "byte_limit=$COMPOSE_LOG_LIMIT_BYTES" in command
