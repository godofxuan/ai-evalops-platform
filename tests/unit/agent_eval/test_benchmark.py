from pathlib import Path

from app.agent_eval.benchmark import load_benchmark_cases, run_adapter_comparison

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = PROJECT_ROOT / "benchmarks" / "agent_eval_v1" / "cases.json"


def test_fixed_benchmark_covers_the_eight_declared_agent_failure_families() -> None:
    cases = load_benchmark_cases(FIXTURE)

    assert [case.family for case in cases] == [
        "direct_lookup",
        "multi_step_retrieval",
        "denied_access",
        "missing_evidence",
        "conflicting_evidence",
        "tool_failure",
        "budget_limit",
        "injection_adversarial",
    ]


def test_custom_and_langgraph_compatibility_adapters_emit_comparable_artifacts() -> None:
    evidence = run_adapter_comparison(FIXTURE)

    assert evidence["benchmark_case_count"] == 8
    assert evidence["comparison"]["intersection_count"] == 8
    assert evidence["adapters"] == [
        "custom-controller",
        "langgraph-adapter",
    ]
    assert evidence["claim_scope"] == (
        "deterministic adapter-contract replay; not runtime performance"
    )
