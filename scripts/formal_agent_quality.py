"""Assess a formal Agent quality A/B and prepare separately held review materials."""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from app.external_harness.formal_quality import (
    FormalArmResult,
    FormalQualityPolicy,
    assess_formal_quality,
    build_blinded_review_packet,
)

BLINDING_KEY_ENV = "EVALOPS_REVIEW_BLINDING_KEY_HEX"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_review_templates(output_dir: Path, packet: dict[str, Any]) -> None:
    fields = (
        "packet_id",
        "reviewer_id",
        "case_id",
        "answer_label",
        "groundedness",
        "citation_correctness",
        "tool_correctness",
        "safety_refusal",
        "overall",
        "notes",
    )
    for reviewer_number in (1, 2):
        path = output_dir / f"review_template_reviewer_{reviewer_number}.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for case in packet["cases"]:
                for answer_label in ("A", "B"):
                    writer.writerow(
                        {
                            "packet_id": packet["packet_id"],
                            "reviewer_id": "",
                            "case_id": case["case_id"],
                            "answer_label": answer_label,
                            "groundedness": "",
                            "citation_correctness": "",
                            "tool_correctness": "",
                            "safety_refusal": "",
                            "overall": "",
                            "notes": "",
                        }
                    )


def _blinding_key() -> bytes | None:
    raw = os.environ.get(BLINDING_KEY_ENV)
    if raw is None:
        return None
    try:
        value = bytes.fromhex(raw)
    except ValueError:
        return None
    return value if len(value) >= 32 else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assess exact-SHA formal Agent quality evidence without silent case loss."
    )
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--evalops-sha", required=True)
    parser.add_argument("--trace-status", choices=("PASS", "FAIL"), default="FAIL")
    parser.add_argument("--failure-matrix-status", choices=("PASS", "FAIL"), default="FAIL")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--write-review-packet", action="store_true")
    args = parser.parse_args(argv)

    baseline = FormalArmResult.model_validate_json(args.baseline.read_text(encoding="utf-8"))
    candidate = FormalArmResult.model_validate_json(args.candidate.read_text(encoding="utf-8"))
    policy = FormalQualityPolicy.model_validate_json(args.policy.read_text(encoding="utf-8"))
    trace_status: Literal["PASS", "FAIL"] = args.trace_status
    failure_matrix_status: Literal["PASS", "FAIL"] = args.failure_matrix_status
    assessment = assess_formal_quality(
        baseline=baseline,
        candidate=candidate,
        policy=policy,
        evalops_sha=str(args.evalops_sha),
        trace_status=trace_status,
        failure_matrix_status=failure_matrix_status,
    )

    if args.write_review_packet:
        key = _blinding_key()
        if key is None:
            print(f"{BLINDING_KEY_ENV} must be a hex value containing at least 32 bytes")
            return 2
        packet, mapping = build_blinded_review_packet(
            baseline=baseline,
            candidate=candidate,
            blinding_key=key,
        )
        _write_json(args.output_dir / "review_packet.json", packet)
        _write_json(args.output_dir / "RESTRICTED_unblinding_map.json", mapping)
        _write_review_templates(args.output_dir, packet)

    _write_json(args.output_dir / "assessment.json", assessment.as_json())
    print(
        f"formal agent quality status: {assessment.status}; "
        f"decision outcome: {assessment.decision.outcome}"
    )
    if assessment.status == "PASS":
        return 0
    return 2 if assessment.status == "INSUFFICIENT_EVIDENCE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
