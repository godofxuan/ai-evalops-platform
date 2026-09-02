from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.product_experiments.spec import ExperimentSpec, load_experiment_spec


def _values() -> dict[str, object]:
    return {
        "schema_version": "evalops.experiment/1.0",
        "experiment_id": "paired-rag-demo-v1",
        "scope": "DEMO",
        "dataset": {"path": "cases.json", "sha256": "a" * 64},
        "policy_path": "policy.json",
        "arms": (
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
        ),
        "evaluators": ("reference_answer", "citation_correctness", "tool_error_rate"),
        "max_concurrency": 8,
    }


def test_spec_is_strict_versioned_and_has_exact_arm_roles() -> None:
    spec = ExperimentSpec.model_validate(_values())

    assert spec.schema_version == "evalops.experiment/1.0"
    assert [arm.label for arm in spec.arms] == ["baseline", "candidate"]

    duplicate = _values()
    arms = list(duplicate["arms"])  # type: ignore[arg-type]
    arms[1] = {**arms[1], "label": "baseline"}
    duplicate["arms"] = tuple(arms)
    with pytest.raises(ValidationError, match="baseline and candidate"):
        ExperimentSpec.model_validate(duplicate)


def test_spec_rejects_literal_secrets_and_unknown_provider_fields() -> None:
    values = _values()
    values["arms"][0]["provider"] = {  # type: ignore[index]
        "type": "http",
        "target_id": "baseline",
        "base_url": "https://rag.example.com",
        "endpoint": "/query",
        "auth_env_var": "BASELINE_RAG_TOKEN",
        "api_key": "must-not-be-stored",
    }

    with pytest.raises(ValidationError):
        ExperimentSpec.model_validate(values)


def test_loader_resolves_paths_relative_to_spec_without_changing_cwd(tmp_path: Path) -> None:
    spec_path = tmp_path / "experiment.json"
    spec_path.write_text(json.dumps(_values()), encoding="utf-8")

    loaded = load_experiment_spec(spec_path)

    assert loaded.dataset_path == tmp_path / "cases.json"
    assert loaded.policy_path == tmp_path / "policy.json"
