from inspect_ai import eval

from app.external_harness.inspect_adapter import convert_inspect_log_to_artifact
from app.external_harness.inspect_task import build_mechanism_smoke_task


def test_real_inspect_task_executes_and_converts(tmp_path) -> None:
    logs = eval(
        build_mechanism_smoke_task(),
        model="mockllm/model",
        log_dir=str(tmp_path / "inspect-logs"),
        display="none",
    )

    assert len(logs) == 1
    assert logs[0].status == "success"
    artifact = convert_inspect_log_to_artifact(logs[0], sample_index=0)
    assert artifact.case_id == "inspect-mechanism-smoke"
    assert artifact.output["completion"] == "deterministic harness answer"
