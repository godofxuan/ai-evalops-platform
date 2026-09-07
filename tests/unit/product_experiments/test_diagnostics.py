from app.product_experiments.diagnostics import build_metric_diagnostics
from app.product_experiments.runner import ExperimentCase, ProviderResult


def test_category_slices_expose_local_regression_and_missing_categories() -> None:
    from app.product_experiments.diagnostics import build_category_diagnostics

    cases = [
        ExperimentCase(case_id=str(index), category=category, prompt="q", reference_answer="a")
        for index, category in enumerate(("fast", "fast", "slow"))
    ]
    observations = {
        "baseline": {
            case.case_id: ProviderResult(answer="a", latency_ms=1.0, cost_usd=0.0) for case in cases
        },
        "candidate": {
            case.case_id: ProviderResult(
                answer="a", latency_ms=0.5 if case.category == "fast" else 2.0
            )
            for case in cases
        },
    }
    slices = build_category_diagnostics(
        cases,
        observations,
        evaluator_names=(),
        minimum_cases=2,
        required_categories=("fast", "slow", "absent"),
    )
    assert sum(item.case_count for item in slices.values()) == 3
    assert slices["fast"].sample_status == "DESCRIPTIVE_ONLY"
    assert slices["fast"].metrics["latency_ms"].candidate_wins == 2
    assert slices["slow"].sample_status == "SMALL_SAMPLE"
    assert slices["slow"].metrics["latency_ms"].candidate_losses == 1
    assert slices["absent"].sample_status == "MISSING_CATEGORY"
    assert slices["absent"].case_count == 0
    assert "cost_usd" in slices["fast"].undersampled_metrics


def test_diagnostic_mean_does_not_overflow_for_finite_measurements() -> None:
    cases = [
        ExperimentCase(case_id=str(index), category="q", prompt="q", reference_answer="a")
        for index in range(2)
    ]
    observations = {
        label: {
            case.case_id: ProviderResult(answer="a", latency_ms=1.0, cost_usd=cost)
            for case in cases
        }
        for label, cost in (("baseline", 0.0), ("candidate", 1e308))
    }
    diagnostic = build_metric_diagnostics(cases, observations, evaluator_names=())["cost_usd"]
    assert diagnostic.mean_paired_delta == 1e308
    assert diagnostic.candidate_losses == 2 and diagnostic.valid_pair_count == 2
