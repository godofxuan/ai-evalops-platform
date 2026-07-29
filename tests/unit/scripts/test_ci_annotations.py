from pathlib import Path

from scripts.ci_annotations import MAX_MESSAGE_CHARS, emit_error, report_junit, report_text


def test_report_junit_emits_escaped_failure_annotation(
    tmp_path: Path,
    capsys: object,
) -> None:
    report = tmp_path / "junit.xml"
    report.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite>
  <testcase
    classname="tests.integration"
    name="test_contract"
    file="tests/test_contract.py"
    line="41"
  >
    <failure message="assert 500 == 201">first line
second: 50%, comma</failure>
  </testcase>
</testsuite>
""",
        encoding="utf-8",
    )

    assert report_junit([report]) == 1

    output = capsys.readouterr().out
    assert "title=tests.integration.test_contract" in output
    assert "file=tests/test_contract.py,line=41" in output
    assert "first line%0Asecond: 50%25, comma" in output


def test_report_text_bounds_diagnostic_output(tmp_path: Path, capsys: object) -> None:
    diagnostic = tmp_path / "compose.txt"
    diagnostic.write_text("prefix-" + ("x" * (MAX_MESSAGE_CHARS + 100)), encoding="utf-8")

    assert report_text(diagnostic, title="Compose: startup") == 1

    output = capsys.readouterr().out
    assert "title=Compose%3A startup" in output
    assert "prefix-" not in output
    assert len(output.split("::", 2)[2].rstrip()) == MAX_MESSAGE_CHARS


def test_missing_reports_are_ignored(tmp_path: Path, capsys: object) -> None:
    missing = tmp_path / "missing.xml"

    assert report_junit([missing]) == 0
    assert report_text(missing, title="missing") == 0
    assert capsys.readouterr().out == ""


def test_emit_error_ignores_non_numeric_line(capsys: object) -> None:
    emit_error(title="failure", message="message", file="test.py", line="unknown")

    output = capsys.readouterr().out
    assert "file=test.py" in output
    assert ",line=" not in output
