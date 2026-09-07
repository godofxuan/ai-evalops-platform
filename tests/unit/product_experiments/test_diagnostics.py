from app.product_experiments.diagnostics import build_metric_diagnostics
from app.product_experiments.runner import ExperimentCase, ProviderResult


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
