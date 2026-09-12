"""Offline reports over single-attempt public pilot ledgers; no target calls."""

from __future__ import annotations

import hashlib
import math
import random
import re
from collections import Counter
from collections.abc import Sequence
from itertools import combinations
from pathlib import Path
from typing import Any

from app.core.strict_json import decode_evidence_json
from app.public_benchmarks.bfcl import grade_case, load_official_checker
from app.public_benchmarks.local_pilot import encoded, read_json, save_new, verify_run
from app.public_benchmarks.ragbench import calibration_metrics, published_prediction_report


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _distribution(values: list[float]) -> dict[str, Any]:
    return {
        "observed_count": len(values),
        "sum": sum(values) if values else None,
        "p50": _quantile(values, 0.5),
        "p95": _quantile(values, 0.95),
    }


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def _timing(results: list[dict[str, Any]]) -> dict[str, Any]:
    called = [result for result in results if result.get("called") is True]
    wall = [
        value * 1000
        for result in called
        if (value := _number(result.get("wall_seconds"))) is not None
    ]
    output: dict[str, Any] = {
        "recorded_called_receipts": len(called),
        "wall_ms": _distribution(wall),
    }
    for source, target, divisor in (
        ("load_duration", "ollama_reported_load_ms", 1_000_000),
        ("total_duration", "ollama_reported_total_ms", 1_000_000),
        ("prompt_eval_duration", "ollama_reported_prompt_eval_ms", 1_000_000),
        ("eval_duration", "ollama_reported_eval_ms", 1_000_000),
        ("prompt_eval_count", "ollama_reported_input_tokens", 1),
        ("eval_count", "ollama_reported_output_tokens", 1),
    ):
        observed = []
        for result in called:
            response = result.get("response")
            if isinstance(response, dict) and (value := _number(response.get(source))) is not None:
                observed.append(value / divisor)
        output[target] = _distribution(observed)
    output["scope"] = "SEQUENTIAL_LOCAL_WALL_AND_UNAUTHENTICATED_SERVER_REPORTED_USAGE"
    output["cost_usd"] = None
    output["electricity_and_hardware_cost"] = None
    output["production_latency_claim_allowed"] = False
    output["measurement_isolation"] = "OBSERVED_NON_ISOLATED"
    output["hardware_fair_speedup_claim_allowed"] = False
    return output


def _paired_comparisons(grouped: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    comparisons = []
    for left_name, right_name in combinations(grouped, 2):
        left = {item["case_id"]: item for item in grouped[left_name]}
        right = {item["case_id"]: item for item in grouped[right_name]}
        shared = sorted(set(left) & set(right))
        strata: dict[str, list[int]] = {}
        for identity in shared:
            if left[identity]["category"] != right[identity]["category"]:
                raise ValueError("paired_category_mismatch")
            strata.setdefault(left[identity]["category"], []).append(
                right[identity]["correct"] - left[identity]["correct"]
            )
        generator = random.Random(20260912)
        samples = []
        if shared:
            for _ in range(2000):
                total = sum(
                    generator.choice(strata[category])
                    for category in sorted(strata)
                    for _ in range(len(strata[category]))
                )
                samples.append(total / len(shared))
        comparisons.append(
            {
                "left_model": left_name,
                "right_model": right_name,
                "paired_case_count": len(shared),
                "left_only_case_ids": sorted(set(left) - set(right)),
                "right_only_case_ids": sorted(set(right) - set(left)),
                "right_minus_left_accuracy": sum(sum(values) for values in strata.values())
                / len(shared)
                if shared
                else None,
                "confidence_interval_95": {
                    "lower": _quantile(samples, 0.025),
                    "upper": _quantile(samples, 0.975),
                },
                "strata": {category: len(values) for category, values in sorted(strata.items())},
                "bootstrap_seed": 20260912,
                "bootstrap_resamples": 2000,
                "method": "paired_case_id_category_stratified_percentile_bootstrap",
                "failed_or_missing_outcomes": "correct=0 in full planned denominator",
                "exploratory_not_confirmatory": True,
                "simultaneous_inference_adjusted": False,
                "causal_or_population_improvement_claim_allowed": False,
            }
        )
    return comparisons


def _rag_prediction(content: str) -> tuple[bool | None, str | None]:
    try:
        value = decode_evidence_json(content.encode())
    except ValueError:
        return None, "INVALID_JUDGE_JSON"
    if not isinstance(value, dict) or set(value) != {"supported", "reason"}:
        return None, "INVALID_JUDGE_SCHEMA"
    if type(value["supported"]) is not bool or not isinstance(value["reason"], str):
        return None, "INVALID_JUDGE_SCHEMA"
    if len(value["reason"]) > 240:
        return None, "INVALID_JUDGE_SCHEMA"
    return value["supported"], None


def _snapshot(run_dir: Path) -> dict[str, str]:
    paths = [run_dir / "plan.json", *sorted((run_dir / "attempts").iterdir())]
    return {
        path.relative_to(run_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


def build_report(run_dir: Path, bfcl_source_dir: Path | None = None) -> dict[str, Any]:
    """Recompute every planned cell, including absent/failed results, without rerunning models."""
    if (run_dir / ".run.lock").exists():
        raise ValueError("run_is_active_report_requires_a_stable_ledger")
    verification = verify_run(run_dir)
    before = _snapshot(run_dir)
    plan = read_json(run_dir / "plan.json")
    benchmarks = {row["benchmark"] for row in plan["requests"]}
    if len(benchmarks) != 1 or not benchmarks <= {"ragbench", "bfcl"}:
        raise ValueError("one_supported_benchmark_per_report_required")
    benchmark = next(iter(benchmarks))
    checker = None
    if benchmark == "bfcl":
        if bfcl_source_dir is None:
            raise ValueError("bfcl_pinned_source_required")
        checker = load_official_checker(bfcl_source_dir)
    identities: set[tuple[str, str]] = set()
    references: dict[str, dict[str, Any]] = {}
    grouped_rows: dict[str, list[dict[str, Any]]] = {}
    grouped_results: dict[str, list[dict[str, Any]]] = {}
    for row in plan["requests"]:
        identity = (row["model"], row["case_id"])
        if identity in identities:
            raise ValueError("duplicate_model_case_cell")
        identities.add(identity)
        reference = row["reference"]
        id_key, category_key = ("id", "category") if benchmark == "bfcl" else ("case_id", "domain")
        if (
            reference.get(id_key) != row["case_id"]
            or reference.get(category_key) != row["category"]
        ):
            raise ValueError("reference_case_identity_mismatch")
        if row["case_id"] in references and references[row["case_id"]] != reference:
            raise ValueError("different_reference_for_same_case")
        references[row["case_id"]] = reference
        path = run_dir / "attempts" / (row["request_id"] + ".result.json")
        result = read_json(path) if path.exists() else None
        status = "NOT_ATTEMPTED"
        if (run_dir / "attempts" / (row["request_id"] + ".intent.json")).exists():
            status = "ATTEMPT_OUTCOME_UNKNOWN"
        if result is not None:
            status = result["status"]
            grouped_results.setdefault(row["model"], []).append(result)
        content = None
        prediction = None
        grading_error = None
        official_valid = None
        parse_failed = False
        safety_rejected = False
        scorer_error = None
        if status == "RESPONDED":
            assert result is not None
            content = result["response"]["message"]["content"]
            if benchmark == "ragbench":
                prediction, grading_error = _rag_prediction(content)
            else:
                assert bfcl_source_dir is not None and checker is not None
                grade = grade_case(reference, content, bfcl_source_dir, checker=checker)
                official_valid = grade["official_valid"]
                parse_failed = grade["parse_failed"]
                safety_rejected = grade["adapter_safety_rejected"]
                scorer_error = grade.get("error_type")
        strict_correct = int(official_valid is True and not parse_failed and not safety_rejected)
        correct = int(official_valid is True)
        if benchmark == "ragbench":
            correct = int(
                prediction is not None
                and type(reference.get("adherence_score")) is bool
                and prediction == reference["adherence_score"]
            )
        detail = {
            "request_id": row["request_id"],
            "case_id": row["case_id"],
            "benchmark": benchmark,
            "category": row["category"],
            "model": row["model"],
            "model_digest": row["model_digest"],
            "status": status,
            "grading_error": grading_error,
            "prediction": prediction,
            "official_valid": official_valid,
            "parse_failed": parse_failed,
            "adapter_safety_rejected": safety_rejected,
            "scorer_error_type": scorer_error,
            "reference_adherence": reference.get("adherence_score"),
            "correct": correct,
            "strict_correct": strict_correct if benchmark == "bfcl" else None,
            "result_sha256": result["result_sha256"] if result else None,
            "response_content_sha256": hashlib.sha256(content.encode()).hexdigest()
            if content is not None
            else None,
        }
        grouped_rows.setdefault(row["model"], []).append(detail)
    models: dict[str, Any] = {}
    for model, details in grouped_rows.items():
        refs = [references[item["case_id"]] for item in details]
        predictions = {item["case_id"]: item["prediction"] for item in details}
        correct = sum(item["correct"] for item in details)
        models[model] = {
            "planned": len(details),
            "correct_full_denominator": correct,
            "accuracy_full_denominator": correct / len(details),
            "statuses": dict(Counter(item["status"] for item in details)),
            "grading_errors": dict(
                Counter(
                    item["grading_error"] for item in details if item["grading_error"] is not None
                )
            ),
            "timing": _timing(grouped_results.get(model, [])),
        }
        models[model]["responded_count"] = sum(item["status"] == "RESPONDED" for item in details)
        models[model]["by_category"] = {
            category: {
                "planned": len(items),
                "correct_full_denominator": sum(i["correct"] for i in items),
                "accuracy_full_denominator": sum(i["correct"] for i in items) / len(items),
            }
            for category in sorted({item["category"] for item in details})
            for items in [[item for item in details if item["category"] == category]]
        }
        if benchmark == "ragbench":
            models[model]["calibration"] = calibration_metrics(refs, predictions)
            models[model]["valid_prediction_count"] = sum(
                item["prediction"] is not None for item in details
            )
            for category, values in models[model]["by_category"].items():
                category_refs = [reference for reference in refs if reference["domain"] == category]
                values["calibration"] = calibration_metrics(
                    category_refs,
                    {ref["case_id"]: predictions[ref["case_id"]] for ref in category_refs},
                )
        else:
            official_count = sum(item["official_valid"] is True for item in details)
            models[model].update(
                {
                    "official_correct_full_denominator": official_count,
                    "official_accuracy_full_denominator": official_count / len(details),
                    "primary_metric": "pinned_official_bfcl_subset_validity",
                    "strict_correct_full_denominator": sum(
                        item["strict_correct"] for item in details
                    ),
                    "strict_accuracy_full_denominator": sum(
                        item["strict_correct"] for item in details
                    )
                    / len(details),
                    "strict_metric_scope": (
                        "OUTPUT_FORMAT_INTEGRATION_CONSTRAINT_NOT_OFFICIAL_TASK_CORRECTNESS"
                    ),
                    "strict_metric": "official_valid_and_not_parse_failed_and_not_safety_rejected",
                    "parse_failed_count": sum(item["parse_failed"] for item in details),
                    "valid_prediction_count": sum(
                        item["official_valid"] is not None for item in details
                    ),
                }
            )
            for category, values in models[model]["by_category"].items():
                items = [item for item in details if item["category"] == category]
                values["strict_correct_full_denominator"] = sum(
                    item["strict_correct"] for item in items
                )
                values["strict_accuracy_full_denominator"] = sum(
                    item["strict_correct"] for item in items
                ) / len(items)
    all_cases = list(references.values())
    report: dict[str, Any] = {
        "schema_version": "evalops.local-public-pilot-report/1.0",
        "benchmark": benchmark,
        "plan_sha256": plan["plan_sha256"],
        "ledger_files_sha256": before,
        "verification": verification,
        "models": models,
        "paired_comparisons": _paired_comparisons(grouped_rows),
        "per_case": [item for rows in grouped_rows.values() for item in rows],
        "source_metadata": plan["metadata"],
        "source_provenance_authenticated": False,
        "human_agreement_claim_allowed": False,
        "formal_quality_claim_allowed": False,
        "production_ready": False,
        "scope": "LOCAL_PUBLIC_SUBSET_EXPLORATORY_NOT_FULL_LEADERBOARD_OR_HUMAN_REVIEW",
    }
    if benchmark == "ragbench":
        report["baselines"] = {
            name: calibration_metrics(all_cases, {case["case_id"]: value for case in all_cases})
            for name, value in (("always_supported", True), ("always_unsupported", False))
        }
        report["published_predictions"] = published_prediction_report(all_cases)
    for comparison in report["paired_comparisons"]:
        comparison["metric"] = (
            "pinned_official_bfcl_subset_validity"
            if benchmark == "bfcl"
            else "agreement_with_public_automated_adherence_full_denominator"
        )
    if _snapshot(run_dir) != before or (run_dir / ".run.lock").exists():
        raise ValueError("run_changed_during_reporting")
    return report


def _report_files(report: dict[str, Any]) -> dict[str, bytes]:
    files = {
        "report.json": encoded({key: value for key, value in report.items() if key != "per_case"}),
        "per-case.json": encoded(report["per_case"]),
    }
    manifest = {
        "schema_version": "evalops.local-public-pilot-report-manifest/1.0",
        "plan_sha256": report["plan_sha256"],
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
        "verification_scope": "OFFLINE_RECOMPUTATION_REQUIRES_SOURCE_LEDGER",
        "source_provenance_authenticated": False,
        "formal_quality_claim_allowed": False,
    }
    files["manifest.json"] = encoded(manifest)
    return files


def write_report(
    run_dir: Path, output: Path, bfcl_source_dir: Path | None = None
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("report_output_already_exists")
    if any(path.is_symlink() or path.is_junction() for path in (output, *output.parents)):
        raise ValueError("linked_report_output_not_allowed")
    report = build_report(run_dir, bfcl_source_dir)
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in _report_files(report).items():
        save_new(output / name, decode_evidence_json(raw))
    return {
        "status": "REPORT_WRITTEN",
        "plan_sha256": report["plan_sha256"],
        "model_count": len(report["models"]),
        "case_cells": len(report["per_case"]),
        "formal_quality_claim_allowed": False,
    }


def verify_report(
    report_dir: Path, run_dir: Path, bfcl_source_dir: Path | None = None
) -> dict[str, Any]:
    if report_dir.is_symlink() or report_dir.is_junction() or not report_dir.is_dir():
        raise ValueError("invalid_report_directory")
    if {path.name for path in report_dir.iterdir()} != {
        "report.json",
        "per-case.json",
        "manifest.json",
    }:
        raise ValueError("unexpected_report_files")
    report = build_report(run_dir, bfcl_source_dir)
    expected = _report_files(report)
    for name, raw in expected.items():
        read_json(report_dir / name)
        if (report_dir / name).read_bytes() != raw:
            raise ValueError("report_differs_from_recomputed_ledger")
    return {
        "status": "REPORT_RECOMPUTED",
        "plan_sha256": report["plan_sha256"],
        "case_cells": len(report["per_case"]),
        "source_provenance_authenticated": False,
        "formal_quality_claim_allowed": False,
    }


def _comparison_source_identity(plan: dict[str, Any], benchmark: str) -> dict[str, str]:
    metadata = plan["metadata"]
    manifest = metadata.get("source_manifest")
    if not isinstance(manifest, dict):
        raise ValueError("comparison_requires_frozen_source_identity")
    repository = (
        manifest.get("source_repository") if benchmark == "bfcl" else manifest.get("dataset")
    )
    revision = manifest.get("source_sha") if benchmark == "bfcl" else manifest.get("revision")
    cases_hash = metadata.get("source_cases_sha256")
    if not isinstance(repository, str) or not repository:
        raise ValueError("comparison_requires_source_repository")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("comparison_requires_exact_source_revision")
    if not isinstance(cases_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", cases_hash):
        raise ValueError("comparison_requires_exact_cases_hash")
    if manifest.get("cases_sha256") != cases_hash:
        raise ValueError("source_manifest_cases_hash_mismatch")
    return {
        "benchmark": benchmark,
        "repository_or_dataset": repository,
        "revision": revision,
        "cases_sha256": cases_hash,
    }


def compare_reports(
    sources: Sequence[tuple[Path, Path]], bfcl_source_dir: Path | None = None
) -> dict[str, Any]:
    """Compare separately verified runs without merging plans or contacting models."""
    if not 2 <= len(sources) <= 8:
        raise ValueError("comparison_requires_two_to_eight_runs")
    models: dict[str, Any] = {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    source_runs: list[dict[str, Any]] = []
    benchmark = None
    source_identity = None
    model_identities: dict[str, str] = {}
    case_ids: set[str] | None = None
    references: dict[str, bytes] = {}
    generation_contracts: dict[str, bytes] = {}
    for run_dir, report_dir in sources:
        verification = verify_report(report_dir, run_dir, bfcl_source_dir)
        report = read_json(report_dir / "report.json")
        rows = read_json(report_dir / "per-case.json")
        if benchmark is not None and benchmark != report["benchmark"]:
            raise ValueError("comparison_benchmark_mismatch")
        benchmark = report["benchmark"]
        plan = read_json(run_dir / "plan.json")
        current_identity = _comparison_source_identity(plan, benchmark)
        if source_identity is not None and source_identity != current_identity:
            raise ValueError("source_identity_mismatch")
        source_identity = current_identity
        current_models: dict[str, str] = {}
        for request_row in plan["requests"]:
            name, model_digest = request_row["model"], request_row["model_digest"]
            case_id = request_row["case_id"]
            reference = encoded(request_row["reference"])
            if case_id in references and references[case_id] != reference:
                raise ValueError("case_reference_mismatch")
            references[case_id] = reference
            request_contract = dict(request_row["request"])
            request_contract.pop("model")
            thinking = request_contract.pop("think", False if name == "qwen2.5:3b" else None)
            if thinking is not False:
                raise ValueError("comparison_requires_explicit_non_thinking_mode")
            contract = encoded(
                {
                    "request": request_contract,
                    "category": request_row["category"],
                    "context_byte_budget": request_row["context_byte_budget"],
                }
            )
            if case_id in generation_contracts and generation_contracts[case_id] != contract:
                raise ValueError("generation_contract_mismatch")
            generation_contracts[case_id] = contract
            if name in current_models and current_models[name] != model_digest:
                raise ValueError("model_digest_changes_within_run")
            current_models[name] = model_digest
        for name, model_digest in current_models.items():
            if name in model_identities or model_digest in model_identities.values():
                raise ValueError("duplicate_model_identity")
            model_identities[name] = model_digest
            current_case_ids = {row["case_id"] for row in plan["requests"] if row["model"] == name}
            if case_ids is not None and case_ids != current_case_ids:
                raise ValueError("planned_case_set_mismatch")
            case_ids = current_case_ids
        models.update(report["models"])
        for row in rows:
            grouped.setdefault(row["model"], []).append(row)
        source_runs.append(
            {
                "plan_sha256": report["plan_sha256"],
                "verification": verification,
                "ledger_files_sha256": report["ledger_files_sha256"],
                "report_files_sha256": {
                    name: hashlib.sha256((report_dir / name).read_bytes()).hexdigest()
                    for name in ("report.json", "per-case.json", "manifest.json")
                },
                "models": list(report["models"]),
            }
        )
    paired = _paired_comparisons(grouped)
    for comparison in paired:
        comparison["metric"] = (
            "pinned_official_bfcl_subset_validity"
            if benchmark == "bfcl"
            else "agreement_with_public_automated_adherence_full_denominator"
        )
    return {
        "schema_version": "evalops.cross-run-public-pilot-comparison/1.0",
        "benchmark": benchmark,
        "source_runs": source_runs,
        "models": models,
        "source_identity": source_identity,
        "model_identities": model_identities,
        "case_count_per_model": len(case_ids or set()),
        "case_ids": sorted(case_ids or set()),
        "paired_comparisons": paired,
        "merged_plan_created": False,
        "request_equivalence": "exact_messages_options_format_category_budget; model excluded; "
        "think=False required except non-thinking qwen2.5:3b may omit it",
        "case_generation_contract_sha256": {
            name: hashlib.sha256(raw).hexdigest() for name, raw in generation_contracts.items()
        },
        "measurement_scope": "CROSS_RUN_NON_SIMULTANEOUS_NON_ISOLATED",
        "source_provenance_authenticated": False,
        "formal_quality_claim_allowed": False,
        "hardware_fair_speedup_claim_allowed": False,
        "causal_improvement_claim_allowed": False,
        "human_agreement_claim_allowed": False,
        "production_ready": False,
    }


def _comparison_files(comparison: dict[str, Any]) -> dict[str, bytes]:
    raw = encoded(comparison)
    return {
        "comparison.json": raw,
        "manifest.json": encoded(
            {
                "schema_version": "evalops.cross-run-public-pilot-manifest/1.0",
                "files": {"comparison.json": hashlib.sha256(raw).hexdigest()},
                "verification_scope": "OFFLINE_RECOMPUTATION_REQUIRES_ALL_SOURCE_LEDGERS",
                "formal_quality_claim_allowed": False,
            }
        ),
    }


def write_comparison(
    sources: Sequence[tuple[Path, Path]], output: Path, bfcl_source_dir: Path | None = None
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("comparison_output_already_exists")
    if any(path.is_symlink() or path.is_junction() for path in (output, *output.parents)):
        raise ValueError("linked_comparison_output_not_allowed")
    comparison = compare_reports(sources, bfcl_source_dir)
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in _comparison_files(comparison).items():
        save_new(output / name, decode_evidence_json(raw))
    return {
        "status": "COMPARISON_WRITTEN",
        "models": list(comparison["models"]),
        "case_count_per_model": comparison["case_count_per_model"],
    }


def verify_comparison(
    output: Path, sources: Sequence[tuple[Path, Path]], bfcl_source_dir: Path | None = None
) -> dict[str, Any]:
    if any(path.is_symlink() or path.is_junction() for path in (output, *output.parents)):
        raise ValueError("linked_comparison_output_not_allowed")
    if not output.is_dir() or {path.name for path in output.iterdir()} != {
        "comparison.json",
        "manifest.json",
    }:
        raise ValueError("unexpected_comparison_files")
    comparison = compare_reports(sources, bfcl_source_dir)
    for name, raw in _comparison_files(comparison).items():
        read_json(output / name)
        if (output / name).read_bytes() != raw:
            raise ValueError("comparison_differs_from_recomputed_ledgers")
    return {
        "status": "COMPARISON_RECOMPUTED",
        "models": list(comparison["models"]),
        "case_count_per_model": comparison["case_count_per_model"],
    }
