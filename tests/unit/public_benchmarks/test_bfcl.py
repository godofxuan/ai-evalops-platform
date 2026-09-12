"""Safety tests and optional real pinned-upstream checker regressions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.public_benchmarks.bfcl import (
    PREFIX,
    BFCLSafetyError,
    BFCLSourceError,
    build_messages,
    grade_case,
    guard_model_output,
    load_official_checker,
    prepare_pilot,
    validate_sources,
)


@pytest.mark.parametrize(
    "response",
    [
        "[foo(x=1+2)]",
        "[foo(x=(lambda: 1))]",
        "[foo(x=__import__('os').system('never-run') + 1)]",
        "x" * 65_537,
    ],
    ids=["binop", "lambda", "malicious-binop", "oversized-output"],
)
def test_rejects_upstream_eval_paths_before_parser(response: str) -> None:
    with pytest.raises(BFCLSafetyError):
        guard_model_output(response)


@pytest.mark.parametrize(
    "response",
    [
        "[foo(x=1, y=-2, z={'a':[True, None]})]",
        "[]",
        "No available function can answer this question.",
        "[triangle_properties.get(side1=5, side2=4, side3=3)]",
    ],
)
def test_non_executable_output_reaches_official_parser(response: str) -> None:
    guard_model_output(response)


def test_missing_source_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(BFCLSourceError, match="missing_source"):
        validate_sources(tmp_path)


def test_tampered_source_fails_before_loading(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text("tampered", encoding="utf-8")
    with pytest.raises(BFCLSourceError, match="source_hash_mismatch:LICENSE"):
        load_official_checker(tmp_path)


def test_unsupported_category_is_not_silently_scored(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported_case_scope"):
        grade_case({"category": "multi_turn"}, "[]", tmp_path)


@pytest.fixture(scope="module")
def actual_upstream() -> tuple[Path, list[dict[str, Any]], dict[str, Any]]:
    root = Path(__file__).resolve().parents[3] / "artifacts/public-benchmark-20260912/bfcl"
    if not (root / "manifest.json").exists():
        pytest.skip("Public BFCL not downloaded; run scripts.prepare_bfcl_pilot --download")
    source_dir = root / "upstream"
    checker = load_official_checker(source_dir)
    cases = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    # Regression examples do not change or supplement the frozen model pilot.
    for category in ("simple_python", "multiple", "parallel", "irrelevance"):
        if any(row["id"] == f"{category}_0" for row in cases):
            continue
        question_path = source_dir / PREFIX / f"data/BFCL_v4_{category}.json"
        question = json.loads(question_path.read_text(encoding="utf-8").splitlines()[0])
        gold = None
        if category != "irrelevance":
            path = source_dir / PREFIX / f"data/possible_answer/BFCL_v4_{category}.json"
            gold = json.loads(path.read_text(encoding="utf-8").splitlines()[0])["ground_truth"]
        cases.append({**question, "category": category, "ground_truth": gold})
    return source_dir, cases, checker


@pytest.mark.parametrize(
    ("case_id", "response", "valid"),
    [
        ("simple_python_0", "[calculate_triangle_area(base=10, height=5)]", True),
        ("simple_python_0", "[calculate_triangle_area(base=10, height=6)]", False),
        ("simple_python_0", "[calculate_triangle_area(base='10', height=5)]", False),
        ("simple_python_0", "[calculate_triangle_area(base=10)]", False),
        ("simple_python_0", "[unknown(base=10, height=5)]", False),
        ("multiple_0", "[triangle_properties.get(side1=5, side2=4, side3=3)]", True),
        ("multiple_0", "[circle_properties.get(radius=5.0)]", False),
        (
            "parallel_0",
            "[spotify.play(artist='Maroon 5', duration=15), "
            "spotify.play(artist='Taylor Swift', duration=20)]",
            True,
        ),
        ("parallel_0", "[spotify.play(artist='Taylor Swift', duration=20)]", False),
        ("irrelevance_0", "[]", True),
        ("irrelevance_0", "No function can calculate the triangle area.", True),
        ("irrelevance_0", "[determine_body_mass_index(weight=10.0, height=5.0)]", False),
    ],
)
def test_actual_pinned_checker(
    actual_upstream: tuple[Path, list[dict[str, Any]], dict[str, Any]],
    case_id: str,
    response: str,
    valid: bool,
) -> None:
    source_dir, cases, checker = actual_upstream
    case = next(row for row in cases if row["id"] == case_id)
    before = json.dumps(case, sort_keys=True)
    result = grade_case(case, response, source_dir, checker=checker)
    assert result["valid"] is valid, result
    assert result["official_valid"] is valid
    assert json.dumps(case, sort_keys=True) == before


def test_actual_parser_never_executes_expression(
    actual_upstream: tuple[Path, list[dict[str, Any]], dict[str, Any]],
    tmp_path: Path,
) -> None:
    source_dir, cases, checker = actual_upstream
    marker = tmp_path / "must-not-exist.txt"
    response = f"[foo(x=__import__('pathlib').Path({str(marker)!r}).write_text('bad') + 1)]"
    result = grade_case(cases[0], response, source_dir, checker=checker)
    assert result["adapter_safety_rejected"] is True
    assert result["official_valid"] is None
    assert result["valid"] is False
    assert not marker.exists()


def test_empty_irrelevance_transport_output_cannot_pass(
    actual_upstream: tuple[Path, list[dict[str, Any]], dict[str, Any]],
) -> None:
    source_dir, cases, checker = actual_upstream
    case = next(row for row in cases if row["id"] == "irrelevance_0")
    result = grade_case(case, "", source_dir, checker=checker)
    assert result["valid"] is False
    assert result["official_valid"] is None
    assert result["error_type"] == "adapter_empty_response"


def test_messages_use_official_prompt_and_never_gold(
    actual_upstream: tuple[Path, list[dict[str, Any]], dict[str, Any]],
) -> None:
    _, cases, checker = actual_upstream
    case = dict(cases[0], ground_truth="PRIVATE-GOLD-MUST-NOT-APPEAR")
    messages = build_messages(case, checker)
    assert messages == cases[0]["messages"]
    assert "PRIVATE-GOLD-MUST-NOT-APPEAR" not in json.dumps(messages)
    assert "Python 3 syntax" in messages[0]["content"]


def test_frozen_manifest_is_reproducible_and_refuses_other_subset(
    actual_upstream: tuple[Path, list[dict[str, Any]], dict[str, Any]],
) -> None:
    source_dir, _, _ = actual_upstream
    manifest = prepare_pilot(source_dir.parent)
    assert manifest["case_count"] == 100
    assert manifest["cases_sha256"] == (
        "e95152b4eb86a2bc7b14b582af439a64b89e323a99ed85f1cf57b59b8f9f6446"
    )
    with pytest.raises(BFCLSourceError, match="refuse_to_overwrite_frozen_pilot"):
        prepare_pilot(source_dir.parent, per_category=24)
