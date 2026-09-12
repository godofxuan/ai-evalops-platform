from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.public_benchmarks.ragbench import (
    DOMAINS,
    REVISION,
    calibration_metrics,
    canonical_bytes,
    select_pilot,
)
from scripts.prepare_ragbench_pilot import load_source_cache


def row(identifier: str, label: bool = True) -> dict[str, object]:
    return {
        "id": identifier,
        "question": "A public question?",
        "documents": ["The provided public evidence."],
        "response": "A supplied response.",
        "adherence_score": label,
        "annotating_model_name": "gpt-4o",
        "generation_model_name": "gpt-3.5-turbo-1106",
        "gpt3_adherence": 1.0,
        "ragas_faithfulness": None,
        "trulens_groundedness": 0.0,
    }


def test_sampling_is_order_and_label_independent_and_keeps_original_content() -> None:
    source = [row(str(index)) for index in range(8)]
    selected = select_pilot({"hotpotqa": source}, per_domain=3)
    changed = [dict(item, adherence_score=False) for item in reversed(source)]
    other = select_pilot({"hotpotqa": changed}, per_domain=3)
    assert [item["case_id"] for item in selected] == [item["case_id"] for item in other]
    assert all(item["documents"] == source[0]["documents"] for item in selected)
    assert all(item["label_origin"] == "PUBLIC_AUTOMATED_ANNOTATION" for item in selected)


def test_calibration_keeps_missing_and_invalid_predictions_out_of_paired_metrics() -> None:
    cases = [
        {"case_id": str(index), "adherence_score": label}
        for index, label in enumerate([True, False, True, False, True, False, None])
    ]
    metrics = calibration_metrics(
        cases, {"0": 1.0, "1": 1.0, "2": 0.0, "3": 0.0, "4": None, "5": float("nan"), "6": 1.0}
    )
    assert metrics["case_count"] == 7
    assert metrics["paired_count"] == 4
    assert metrics["missing_prediction_count"] == 1
    assert metrics["invalid_prediction_count"] == 1
    assert metrics["invalid_reference_count"] == 1
    assert metrics["accuracy"] == 0.5
    assert metrics["confusion"] == {
        "true_supported": 1,
        "true_unsupported": 1,
        "false_supported": 1,
        "false_unsupported": 1,
    }
    assert metrics["false_supported_rate"] == 0.5
    assert metrics["human_agreement_claim_allowed"] is False


def test_calibration_rejects_unknown_case_predictions() -> None:
    with pytest.raises(ValueError, match="Unknown"):
        calibration_metrics([{"case_id": "known", "adherence_score": True}], {"other": 1.0})


@pytest.mark.parametrize("mutation", ["hash", "revision", "truncated", "sequence", "incomplete"])
def test_real_saved_page_parser_rejects_incomplete_or_modified_evidence(
    tmp_path: Path, mutation: str
) -> None:
    receipts = []
    for domain in DOMAINS:
        name = f"{domain}-test-00000.json"
        payload = {
            "num_rows_total": 1,
            "partial": False,
            "rows": [{"row_idx": 0, "truncated_cells": [], "row": row("1")}],
        }
        if domain == "hotpotqa":
            if mutation == "truncated":
                payload["rows"][0]["truncated_cells"] = ["documents"]
            if mutation == "sequence":
                payload["rows"][0]["row_idx"] = 1
            if mutation == "incomplete":
                payload["num_rows_total"] = 2
        raw = canonical_bytes(payload)
        (tmp_path / name).write_bytes(raw)
        receipts.append(
            {"file": name, "sha256": hashlib.sha256(raw).hexdigest(), "response_revision": REVISION}
        )
    if mutation == "hash":
        (tmp_path / receipts[0]["file"]).write_bytes(b"{}")
    if mutation == "revision":
        receipts[0]["response_revision"] = "0" * 40
    (tmp_path / "receipts.json").write_bytes(canonical_bytes(receipts))
    with pytest.raises(ValueError):
        load_source_cache(tmp_path)


def test_duplicate_source_ids_are_rejected_before_sampling() -> None:
    with pytest.raises(ValueError, match="unique"):
        select_pilot({"hotpotqa": [row("1"), row("1")]}, per_domain=1)


def test_single_class_and_empty_predictions_do_not_claim_balanced_accuracy() -> None:
    cases = [{"case_id": "only", "adherence_score": True}]
    empty = calibration_metrics(cases, {})
    assert empty["accuracy"] is None and empty["paired_count"] == 0
    all_supported = calibration_metrics(cases, {"only": True})
    assert all_supported["accuracy"] == 1.0
    assert all_supported["balanced_accuracy"] is None
    assert all_supported["cohen_kappa"] is None


def test_two_generated_responses_are_one_question_and_selection_ignores_labels() -> None:
    first = row("one")
    second = dict(first, generation_model_name="second-model", response="Other fixed response.")
    selected = select_pilot({"finqa": [first, second]}, per_domain=1)
    reverse = select_pilot({"finqa": [dict(second, adherence_score=False), first]}, per_domain=1)
    assert len(selected) == 1
    assert selected[0]["generation_model_name"] == reverse[0]["generation_model_name"]
    assert selected[0]["response"] == reverse[0]["response"]


def test_prepare_cli_runs_offline_from_real_saved_pages_and_preserves_null_predictions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    receipts = []
    for domain in DOMAINS:
        name = f"{domain}-test-00000.json"
        payload = {
            "num_rows_total": 100,
            "partial": False,
            "rows": [
                {"row_idx": index, "truncated_cells": [], "row": row(str(index), index % 2 == 0)}
                for index in range(100)
            ],
        }
        raw = canonical_bytes(payload)
        (source / name).write_bytes(raw)
        receipts.append(
            {"file": name, "sha256": hashlib.sha256(raw).hexdigest(), "response_revision": REVISION}
        )
    (source / "receipts.json").write_bytes(canonical_bytes(receipts))
    output = tmp_path / "pilot"
    command = [
        sys.executable,
        "-m",
        "scripts.prepare_ragbench_pilot",
        "--source-dir",
        str(source),
        "--output-dir",
        str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    cases = json.loads((output / "cases.json").read_bytes())
    report = json.loads((output / "published-predictions-report.json").read_bytes())
    assert len(cases) == 300
    assert report["groups"]["all"]["ragas_faithfulness"]["paired_count"] == 0
    assert report["groups"]["all"]["ragas_faithfulness"]["missing_prediction_count"] == 300
    original = (output / "cases.json").read_bytes()
    refused = subprocess.run(command, capture_output=True, text=True, check=False)
    assert refused.returncode != 0
    assert (output / "cases.json").read_bytes() == original
