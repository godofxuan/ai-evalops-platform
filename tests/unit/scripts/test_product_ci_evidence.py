import json
import xml.etree.ElementTree as ET

from scripts.product_ci_evidence import capture


def test_capture_preserves_real_outcomes_without_payloads(tmp_path, monkeypatch):
    source = tmp_path / "input"
    source.mkdir()
    (source / "junit-unit.xml").write_text(
        '<testsuites><testsuite><testcase classname="tests.unit.contract" name="ok"/>'
        '<testcase classname="tests.unit.contract" name="bad">'
        '<failure message="PRIVATE_SECRET">RAW_ANSWER</failure>'
        "<system-out>BEARER_SECRET</system-out></testcase>"
        '<testcase classname="tests.unit.contract" name="skip">'
        '<skipped message="DB_PASSWORD"/></testcase></testsuite></testsuites>'
    )
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    output = tmp_path / "out"
    result = capture(output, source)
    assert result.get("code_sha") == "a" * 40
    assert result["junit"]["junit-unit.xml"]["state"] == "FAILED"
    assert result["junit"]["junit-unit.xml"]["counts"] == {
        "tests": 3,
        "failures": 1,
        "errors": 0,
        "skipped": 1,
    }
    xml = (output / "junit-unit.xml").read_text()
    assert len(ET.fromstring(xml).findall(".//testcase")) == 3
    assert all(
        secret not in xml
        for secret in ["PRIVATE_SECRET", "RAW_ANSWER", "BEARER_SECRET", "DB_PASSWORD"]
    )
    assert result["junit"]["junit-product-experiment-persistence.xml"]["state"] == "NOT_GENERATED"
    assert json.loads((output / "identity.json").read_text())["code_sha"] == "a" * 40


def test_empty_or_absent_junit_is_never_pass(tmp_path):
    (tmp_path / "junit-unit.xml").write_text("<testsuites/>")
    result = capture(tmp_path / "out", tmp_path)
    assert result.get("junit", {}).get("junit-unit.xml", {}).get("state") == "EMPTY_NOT_VERIFIED"


def test_capture_reliability_phase_keeps_only_allowlisted_synthetic_fields(tmp_path):
    phase = (
        "SYNTHETIC_RELIABILITY_PANEL_VERIFIED task=QA "
        "scenario=complete trials=2 private_recomputed=true"
    )
    (tmp_path / "junit-product-experiment-persistence.xml").write_text(
        '<testsuites><testsuite><testcase name="repeat"><system-out>'
        + phase
        + " PRIVATE_CANARY</system-out></testcase></testsuite></testsuites>"
    )
    result = capture(tmp_path / "out", tmp_path)
    entry = result["junit"]["junit-product-experiment-persistence.xml"]
    assert entry["verified_reliability_phases"] == [phase]
    assert "PRIVATE_CANARY" not in json.dumps(result)
