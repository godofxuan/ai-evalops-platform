from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.public_benchmarks.local_pilot import execute_plan, write_plan
from app.public_benchmarks.pilot_report import compare_reports, write_report
from app.public_benchmarks.ragbench import REVISION


def make_run(
    root: Path,
    model: str,
    *,
    fail_second: bool = False,
    row_changes: dict[str, Any] | None = None,
    request_changes: dict[str, Any] | None = None,
    metadata_changes: dict[str, Any] | None = None,
    count: int = 2,
) -> tuple[Path, Path]:
    rows = []
    for index in range(count):
        identity = f"public-{index}"
        domain = "hotpotqa" if index == 0 else "finqa"
        request: dict[str, Any] = {
            "model": model,
            "stream": False,
            "keep_alive": "5m",
            "messages": [{"role": "user", "content": identity}],
            "options": {"temperature": 0, "seed": 20260912, "num_ctx": 8192, "num_predict": 512},
        }
        if model != "qwen2.5:3b":
            request["think"] = False
        if request_changes:
            request.update(request_changes)
        row = {
            "benchmark": "ragbench",
            "case_id": identity,
            "category": domain,
            "model": model,
            "model_digest": hashlib.sha256(model.encode()).hexdigest(),
            "context_byte_budget": 6000,
            "request": request,
            "reference": {
                "case_id": identity,
                "domain": domain,
                "adherence_score": index == 0,
                "published_predictions": {
                    "gpt3_adherence": 1.0,
                    "ragas_faithfulness": None,
                    "trulens_groundedness": 0.0,
                },
            },
        }
        if row_changes:
            row.update(row_changes)
        rows.append(row)
    metadata = {
        "evidence_kind": "TEST_FIXTURE_NOT_MODEL_BENCHMARK",
        "source_manifest": {
            "dataset": "galileo-ai/ragbench",
            "revision": REVISION,
            "cases_sha256": "b" * 64,
            "split": "test",
        },
        "source_cases_sha256": "b" * 64,
    }
    if metadata_changes:
        metadata.update(metadata_changes)
    plan = write_plan(root / "input", rows=rows, metadata=metadata)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test"})
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": model, "digest": hashlib.sha256(model.encode()).hexdigest()}
                    ]
                },
            )
        request_body = json.loads(request.content)
        last = request_body["messages"][-1]["content"]
        if fail_second and last == "public-1":
            raise httpx.ReadTimeout("boundary fixture timeout")
        return httpx.Response(
            200,
            json={
                "model": model,
                "done": True,
                "done_reason": "stop",
                "message": {
                    "content": json.dumps({"supported": last != "public-1", "reason": "test"})
                },
            },
        )

    run, report = root / "run", root / "report"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        execute_plan(plan, run, client=client)
    write_report(run, report)
    return run, report


def file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_two_verified_real_ledgers_compare_without_merging_or_rewriting_inputs(
    tmp_path: Path,
) -> None:
    left = make_run(tmp_path / "left", "qwen2.5:3b")
    right = make_run(tmp_path / "right", "qwen3:8b", fail_second=True)
    before = file_hashes(tmp_path)
    comparison = compare_reports([left, right])
    assert comparison["case_count_per_model"] == 2
    assert comparison["models"]["qwen2.5:3b"]["correct_full_denominator"] == 2
    assert comparison["models"]["qwen3:8b"]["correct_full_denominator"] == 1
    assert comparison["paired_comparisons"][0]["paired_case_count"] == 2
    assert comparison["paired_comparisons"][0]["right_minus_left_accuracy"] == -0.5
    assert (
        comparison["source_runs"][0]["plan_sha256"] != comparison["source_runs"][1]["plan_sha256"]
    )
    assert comparison["merged_plan_created"] is False
    assert comparison["measurement_scope"] == "CROSS_RUN_NON_SIMULTANEOUS_NON_ISOLATED"
    assert file_hashes(tmp_path) == before


def test_different_frozen_source_revision_is_not_a_valid_cross_run_comparison(
    tmp_path: Path,
) -> None:
    left = make_run(tmp_path / "left", "qwen2.5:3b")
    right = make_run(
        tmp_path / "right",
        "qwen3:8b",
        metadata_changes={
            "source_manifest": {
                "dataset": "galileo-ai/ragbench",
                "revision": "0" * 40,
                "cases_sha256": "b" * 64,
                "split": "test",
            }
        },
    )
    with pytest.raises(ValueError, match="source_identity_mismatch"):
        compare_reports([left, right])


def test_a_second_run_of_the_same_model_cannot_overwrite_stats_or_double_the_sample(
    tmp_path: Path,
) -> None:
    left = make_run(tmp_path / "left", "qwen2.5:3b")
    right = make_run(tmp_path / "right", "qwen2.5:3b", fail_second=True)
    with pytest.raises(ValueError, match="duplicate_model_identity"):
        compare_reports([left, right])


def test_missing_planned_cases_are_not_silently_reduced_to_an_intersection(tmp_path: Path) -> None:
    left = make_run(tmp_path / "left", "qwen2.5:3b")
    right = make_run(tmp_path / "right", "qwen3:8b", count=1)
    with pytest.raises(ValueError, match="planned_case_set_mismatch"):
        compare_reports([left, right])


def test_same_case_id_with_changed_reference_is_rejected_even_with_same_claimed_source_hash(
    tmp_path: Path,
) -> None:
    left = make_run(tmp_path / "left", "qwen2.5:3b", count=1)
    right = make_run(
        tmp_path / "right",
        "qwen3:8b",
        count=1,
        row_changes={
            "reference": {
                "case_id": "public-0",
                "domain": "hotpotqa",
                "adherence_score": False,
                "published_predictions": {
                    "gpt3_adherence": 1.0,
                    "ragas_faithfulness": None,
                    "trulens_groundedness": 0.0,
                },
            }
        },
    )
    with pytest.raises(ValueError, match="case_reference_mismatch"):
        compare_reports([left, right])


@pytest.mark.parametrize(
    "changes",
    [
        {"messages": [{"role": "user", "content": "Changed question"}]},
        {"options": {"temperature": 0, "seed": 7, "num_ctx": 8192, "num_predict": 512}},
        {"format": "json"},
        {"keep_alive": "10m"},
        {"think": True},
    ],
)
def test_same_cases_with_different_generation_contract_cannot_be_compared(
    tmp_path: Path,
    changes: dict[str, Any],
) -> None:
    left = make_run(tmp_path / "left", "qwen2.5:3b", count=1)
    right = make_run(tmp_path / "right", "qwen3:8b", count=1, request_changes=changes)
    with pytest.raises(ValueError, match="generation_contract_mismatch|thinking"):
        compare_reports([left, right])


def test_comparison_export_recomputes_from_ledgers_and_rejects_rehashed_changes(
    tmp_path: Path,
) -> None:
    from app.public_benchmarks.local_pilot import encoded
    from app.public_benchmarks.pilot_report import verify_comparison, write_comparison

    sources = [make_run(tmp_path / "left", "qwen2.5:3b"), make_run(tmp_path / "right", "qwen3:8b")]
    output = tmp_path / "comparison"
    write_comparison(sources, output)
    assert verify_comparison(output, sources)["status"] == "COMPARISON_RECOMPUTED"
    with pytest.raises(FileExistsError):
        write_comparison(sources, output)
    document = json.loads((output / "comparison.json").read_bytes())
    document["models"]["qwen3:8b"]["correct_full_denominator"] = 999
    (output / "comparison.json").write_bytes(encoded(document))
    manifest = json.loads((output / "manifest.json").read_bytes())
    manifest["files"]["comparison.json"] = hashlib.sha256(
        (output / "comparison.json").read_bytes()
    ).hexdigest()
    (output / "manifest.json").write_bytes(encoded(manifest))
    with pytest.raises(ValueError, match="comparison_differs_from_recomputed"):
        verify_comparison(output, sources)


def test_cross_run_cli_exports_and_verifies_without_model_or_git_access(tmp_path: Path) -> None:
    import subprocess
    import sys

    sources = [make_run(tmp_path / "left", "qwen2.5:3b"), make_run(tmp_path / "right", "qwen3:8b")]
    args = []
    for run, report in sources:
        args.extend(["--run-dir", str(run), "--report-dir", str(report)])
    output = tmp_path / "export"
    args.extend(["--output-dir", str(output)])
    for operation in ("compare", "verify"):
        done = subprocess.run(
            [sys.executable, "-m", "scripts.compare_local_public_benchmarks", operation, *args],
            cwd=Path(__file__).resolve().parents[3],
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0, done.stderr
        assert json.loads(done.stdout)["status"] in {"COMPARISON_WRITTEN", "COMPARISON_RECOMPUTED"}
