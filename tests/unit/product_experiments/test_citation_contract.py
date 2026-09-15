"""Actual module regression, not copied function excerpts."""

import pytest

from app.product_experiments.evaluators import (
    CitationCorrectnessEvaluator,
    citation_evidence_scores,
)
from app.product_experiments.runner import ExperimentCase, ProviderResult
from app.targets.base import TargetInvalidResponseError


@pytest.mark.parametrize(
    "citation",
    [
        {"source_id": "wrong", "id": "gold"},
        {"source_id": 123},
        {"id": "   "},
    ],
)
def test_actual_target_rejects_invalid_citation_identity(citation):
    with pytest.raises(TargetInvalidResponseError) as rejected:
        ProviderResult.from_target({"answer": "ok", "citations": [citation], "latency_ms": 1.0})
    assert rejected.value.code == "target_citation_invalid"


def test_registered_and_diagnostic_scorers_reject_the_same_alias_conflict():
    case = ExperimentCase(
        case_id="one",
        category="test",
        prompt="q",
        reference_answer="ok",
        expected_citation_ids=("gold",),
    )
    result = ProviderResult(
        answer="ok", citations=[{"source_id": "wrong", "id": "gold"}], latency_ms=1.0
    )
    for score in (CitationCorrectnessEvaluator().evaluate, citation_evidence_scores):
        with pytest.raises(TargetInvalidResponseError) as rejected:
            score(case, result)
        assert rejected.value.code == "target_citation_invalid"


@pytest.mark.parametrize(
    "citations,expected",
    [
        ([{"source_id": "gold"}], (1.0, 1.0)),
        ([{"id": "gold"}], (1.0, 1.0)),
        ([{"source_id": "gold", "id": "gold"}], (1.0, 1.0)),
        ([{"id": "gold"}, {"id": "gold"}], (1.0, 1.0)),
        ([{"id": "gold"}, {"id": "extra"}], (1.0, 0.5)),
        ([{"id": "gold"}, {}], (1.0, 0.5)),
        ([], (0.0, 0.0)),
    ],
)
def test_canonical_recall_and_precision_are_distinct(citations, expected):
    case = ExperimentCase(
        case_id="one",
        category="test",
        prompt="q",
        reference_answer="ok",
        expected_citation_ids=("gold",),
    )
    result = ProviderResult.from_target({"answer": "ok", "citations": citations, "latency_ms": 1.0})
    assert citation_evidence_scores(case, result) == expected
    assert CitationCorrectnessEvaluator().evaluate(case, result) == expected[0]


def test_legacy_rules_are_explicit_and_unknown_versions_fail_closed():
    from app.product_experiments.citations import LEGACY_SCORER
    from app.product_experiments.evaluators import registered_evaluators
    from app.product_experiments.runner import score_product_case

    case = ExperimentCase(
        case_id="one",
        category="test",
        prompt="q",
        reference_answer="ok",
        expected_citation_ids=("gold",),
    )
    result = ProviderResult.from_target(
        {"answer": "ok", "latency_ms": 1.0, "citations": [{"source_id": "wrong", "id": "gold"}]},
        scorer_version=LEGACY_SCORER,
    )
    evaluators = registered_evaluators(("citation_correctness",), scorer_version=LEGACY_SCORER)
    assert evaluators[0].evaluate(case, result) == 1.0  # Frozen legacy registration bug.
    assert (
        score_product_case(case, result, evaluators=evaluators, scorer_version=LEGACY_SCORER)[
            "citation_correctness"
        ]
        == 0.0
    )
    with pytest.raises(ValueError, match="unsupported"):
        registered_evaluators(("citation_correctness",), scorer_version="unknown")


async def test_local_execution_export_and_offline_rescore_preserve_invalid_case(tmp_path):
    import hashlib
    import json

    from app.product_experiments.learning_workflow import load_evidence
    from app.product_experiments.runner import run_experiment
    from scripts.run_product_experiment import write_product_artifacts
    from tests.unit.product_experiments.test_runner import _experiment

    path = _experiment(tmp_path)
    spec = json.loads(path.read_bytes())
    dataset = tmp_path / "cases.json"
    cases = json.loads(dataset.read_bytes())
    cases[0]["metadata"]["fixture_profiles"]["candidate"]["citations"] = [
        {"source_id": "wrong", "id": "gold"}
    ]
    raw = json.dumps(cases).encode()
    dataset.write_bytes(raw)
    spec["dataset"]["sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(spec), encoding="utf-8")
    result = await run_experiment(path, evalops_sha="e" * 40)
    assert result.status == "EXECUTION_FAILED" and result.case_count == 120
    assert len(result.execution_errors) == 1
    assert result.execution_errors[0].error_code == "target_citation_invalid"
    assert sum(map(len, result.observations.values())) == 239
    write_product_artifacts(
        result,
        output_dir=tmp_path / "bundle",
        command="synthetic regression",
        export_mode="private",
    )
    evidence = load_evidence(tmp_path / "bundle", dataset_path=dataset)
    assert evidence.result == result
