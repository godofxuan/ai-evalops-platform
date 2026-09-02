from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.product_experiments.runner import DatasetIntegrityError, run_experiment

CATEGORIES = (
    "basic",
    "semantic",
    "completeness",
    "conflicting_information",
    "high_level",
    "information_not_found",
)


def _write_json(path: Path, value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    path.write_text(payload + "\n", encoding="utf-8", newline="\n")
    return hashlib.sha256((payload + "\n").encode()).hexdigest()


def _case(index: int) -> dict[str, object]:
    category = CATEGORIES[index % len(CATEGORIES)]
    answer = f"answer-{index}"
    citation_id = f"source-{index}"
    return {
        "case_id": f"case-{index:03d}",
        "category": category,
        "prompt": f"Question {index}?",
        "reference_answer": answer,
        "expected_citation_ids": [citation_id],
        "metadata": {
            "fixture_profiles": {
                "baseline": {
                    "answer": answer,
                    "citations": [{"source_id": citation_id}],
                    "latency_ms": 40,
                    "cost_usd": 0.01,
                },
                "candidate": {
                    "answer": answer,
                    "citations": [{"source_id": citation_id}],
                    "latency_ms": 44,
                    "cost_usd": 0.011,
                },
            }
        },
    }


def _experiment(tmp_path: Path, *, scope: str = "DEMO") -> Path:
    dataset_path = tmp_path / "cases.json"
    dataset_sha = _write_json(dataset_path, [_case(index) for index in range(120)])
    policy = {
        "schema_version": "formal-agent-quality-policy/1.0",
        "minimum_common_cases": 120,
        "minimum_cases_per_category": 20,
        "required_categories": list(CATEGORIES),
        "bootstrap_resamples": 200,
        "bootstrap_seed": 20260902,
        "task_success_ci_lower_min": 0,
        "citation_correctness_ci_lower_min": -0.02,
        "tool_error_rate_ci_upper_max": 0.02,
        "latency_p95_relative_delta_max": 0.25,
        "cost_mean_relative_delta_max": 0.25,
        "require_exact_case_set": True,
    }
    _write_json(tmp_path / "policy.json", policy)
    spec = {
        "schema_version": "evalops.experiment/1.0",
        "experiment_id": "paired-rag-demo-v1",
        "scope": scope,
        "dataset": {"path": "cases.json", "sha256": dataset_sha},
        "policy_path": "policy.json",
        "arms": [
            {
                "label": "baseline",
                "source_repository": "demo://baseline",
                "source_sha": "b" * 40,
                "provider": {"type": "fixture", "profile": "baseline"},
            },
            {
                "label": "candidate",
                "source_repository": "demo://candidate",
                "source_sha": "c" * 40,
                "provider": {"type": "fixture", "profile": "candidate"},
            },
        ],
        "evaluators": ["reference_answer", "citation_correctness", "tool_error_rate"],
        "max_concurrency": 8,
    }
    spec_path = tmp_path / "experiment.json"
    _write_json(spec_path, spec)
    return spec_path


@pytest.mark.asyncio
async def test_demo_runs_120_paired_cases_and_preserves_claim_boundary(tmp_path: Path) -> None:
    result = await run_experiment(_experiment(tmp_path), evalops_sha="e" * 40)

    assert result.status == "DEMO_PASS"
    assert result.scope == "DEMO"
    assert result.case_count == 120
    assert result.automated_assessment["status"] == "PASS"
    assert result.automated_assessment["decision"]["formal_ab_eligible"] is False
    assert result.automated_assessment["decision_outcome"] == "INPUT_BLOCKED"
    assert result.human_review_status == "PENDING"
    assert result.formal_quality_claim_allowed is False
    assert result.production_ready is False
    assert len(result.arms["baseline"].cases) == 120
    assert len(result.arms["candidate"].cases) == 120


@pytest.mark.asyncio
async def test_dataset_digest_mismatch_fails_before_provider_execution(tmp_path: Path) -> None:
    spec_path = _experiment(tmp_path)
    values = json.loads(spec_path.read_text(encoding="utf-8"))
    values["dataset"]["sha256"] = "0" * 64
    _write_json(spec_path, values)

    with pytest.raises(DatasetIntegrityError, match="dataset SHA-256 mismatch"):
        await run_experiment(spec_path, evalops_sha="e" * 40)


@pytest.mark.asyncio
async def test_missing_http_credential_returns_machine_actionable_input_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = _experiment(tmp_path, scope="FORMAL")
    values = json.loads(spec_path.read_text(encoding="utf-8"))
    values["arms"][1]["provider"] = {
        "type": "http",
        "target_id": "candidate-rag",
        "base_url": "https://rag.example.com",
        "endpoint": "/v1/query",
        "auth_env_var": "CANDIDATE_RAG_TOKEN",
    }
    _write_json(spec_path, values)
    monkeypatch.delenv("CANDIDATE_RAG_TOKEN", raising=False)

    result = await run_experiment(spec_path, evalops_sha="e" * 40)

    assert result.status == "INPUT_REQUIRED"
    assert result.input_requirements == [
        {
            "arm": "candidate",
            "code": "MISSING_CREDENTIAL_ENV",
            "environment_variable": "CANDIDATE_RAG_TOKEN",
        }
    ]
    assert result.formal_quality_claim_allowed is False
