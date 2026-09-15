"""Gate-policy unit fixtures, not evidence that Windows links were exercised."""

from pathlib import Path

import pytest

from scripts.windows_link_gate import EXPECTED_CASES, verify_junit


def test_windows_gate_rejects_a_skipped_required_link_case(tmp_path: Path) -> None:
    names = sorted(EXPECTED_CASES)
    content = (
        "<testsuites><testsuite>"
        + "".join(
            f'<testcase name="{name}">'
            + ('<skipped message="privilege unavailable"/>' if i == 0 else "")
            + "</testcase>"
            for i, name in enumerate(names)
        )
        + "</testsuite></testsuites>"
    )
    path = tmp_path / "unit-fixture.xml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="skipped"):
        verify_junit(path)


@pytest.mark.parametrize("defect", ["missing", "duplicate", "failure", "error", "none"])
def test_windows_gate_checks_exact_cases_and_failures(tmp_path: Path, defect: str) -> None:
    names = sorted(EXPECTED_CASES)
    if defect == "missing":
        names.pop()
    elif defect == "duplicate":
        names[-1] = names[0]
    content = (
        "<testsuites><testsuite>"
        + "".join(
            f'<testcase name="{name}">'
            + (f"<{defect}/>" if i == 0 and defect in {"failure", "error"} else "")
            + "</testcase>"
            for i, name in enumerate(names)
        )
        + "</testsuite></testsuites>"
    )
    path = tmp_path / "unit-fixture.xml"
    path.write_text(content, encoding="utf-8")
    if defect == "none":
        assert verify_junit(path) == 5
    else:
        with pytest.raises(ValueError):
            verify_junit(path)
