from __future__ import annotations

import csv
import json

from app.external_harness.formal_quality import FormalQualityPolicy
from scripts import formal_agent_quality
from tests.unit.external_harness.test_formal_quality import _arm, _policy


def test_cli_writes_assessment_and_separate_blinded_review_materials(
    tmp_path, monkeypatch
) -> None:
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    policy_path = tmp_path / "policy.json"
    output_dir = tmp_path / "output"
    baseline_path.write_text(_arm(candidate=False).model_dump_json(), encoding="utf-8")
    candidate_path.write_text(_arm(candidate=True).model_dump_json(), encoding="utf-8")
    policy: FormalQualityPolicy = _policy()
    policy_path.write_text(policy.model_dump_json(), encoding="utf-8")
    monkeypatch.setenv("EVALOPS_REVIEW_BLINDING_KEY_HEX", "22" * 32)

    exit_code = formal_agent_quality.main(
        [
            "--baseline",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
            "--policy",
            str(policy_path),
            "--evalops-sha",
            "e" * 40,
            "--trace-status",
            "PASS",
            "--failure-matrix-status",
            "PASS",
            "--output-dir",
            str(output_dir),
            "--write-review-packet",
        ]
    )

    assert exit_code == 0
    assessment = json.loads((output_dir / "assessment.json").read_text(encoding="utf-8"))
    packet = json.loads((output_dir / "review_packet.json").read_text(encoding="utf-8"))
    mapping = json.loads(
        (output_dir / "RESTRICTED_unblinding_map.json").read_text(encoding="utf-8")
    )
    assert assessment["status"] == "PASS"
    assert mapping["packet_sha256"] == packet["packet_sha256"]
    assert packet["packet_id"] == mapping["packet_id"]

    for reviewer_number in (1, 2):
        template = output_dir / f"review_template_reviewer_{reviewer_number}.csv"
        with template.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 200
        assert {row["answer_label"] for row in rows} == {"A", "B"}
        assert {row["packet_id"] for row in rows} == {packet["packet_id"]}


def test_cli_fails_closed_without_blinding_key(tmp_path, monkeypatch) -> None:
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    policy_path = tmp_path / "policy.json"
    baseline_path.write_text(_arm(candidate=False).model_dump_json(), encoding="utf-8")
    candidate_path.write_text(_arm(candidate=True).model_dump_json(), encoding="utf-8")
    policy_path.write_text(_policy().model_dump_json(), encoding="utf-8")
    monkeypatch.delenv("EVALOPS_REVIEW_BLINDING_KEY_HEX", raising=False)

    exit_code = formal_agent_quality.main(
        [
            "--baseline",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
            "--policy",
            str(policy_path),
            "--evalops-sha",
            "e" * 40,
            "--output-dir",
            str(tmp_path / "output"),
            "--write-review-packet",
        ]
    )

    assert exit_code == 2
    assert not (tmp_path / "output" / "review_packet.json").exists()
