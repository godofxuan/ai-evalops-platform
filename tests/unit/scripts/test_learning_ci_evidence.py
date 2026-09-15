import json
from pathlib import Path

from scripts.product_ci_evidence import capture


def test_only_fixed_learning_phase_markers_are_retained(tmp_path: Path):
    junit = tmp_path / "junit"
    junit.mkdir()
    marker = (
        "SYNTHETIC_LEARNING_WORKFLOW_VERIFIED task=QA scenario=complete "
        "trial=1 private_recomputed=true diagnostics_recomputed=true"
    )
    (junit / "junit-unit.xml").write_text(
        '<testsuite><testcase name="workflow"><system-out>'
        + marker
        + "\nprivate-answer-and-token\nSYNTHETIC_LEARNING_WORKFLOW_VERIFIED task=PRIVATE "
        "scenario=complete trial=1 private_recomputed=true diagnostics_recomputed=true"
        "</system-out></testcase></testsuite>",
        encoding="utf-8",
    )
    output = tmp_path / "retained"
    identity = capture(output, junit)
    assert identity["junit"]["junit-unit.xml"]["verified_learning_phases"] == [marker]
    assert "private-answer-and-token" not in json.dumps(identity)
    assert b"private-answer-and-token" not in (output / "junit-unit.xml").read_bytes()
