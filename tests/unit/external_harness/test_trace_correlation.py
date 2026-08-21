from app.external_harness.trace_correlation import (
    build_remote_parent_link,
    export_without_breaking_evaluation,
    safe_correlation_attributes,
)


def test_trace_link_and_export_failure_preserve_evaluation_control_flow() -> None:
    trace_id = "1" * 32
    span_id = "2" * 16
    link = build_remote_parent_link(f"00-{trace_id}-{span_id}-01")
    attributes = safe_correlation_attributes(
        eval_run_id="eval-1",
        case_id="case-1",
        attempt_id="attempt-1",
        producer_git_sha="e" * 40,
    )

    assert f"{link.context.trace_id:032x}" == trace_id
    assert f"{link.context.span_id:016x}" == span_id
    assert link.context.is_remote is True
    assert set(attributes) == {
        "eval.run_id",
        "eval.case_id",
        "eval.attempt_id",
        "producer.git.sha",
    }

    class BrokenExporter:
        def export(self, _spans: object) -> None:
            raise RuntimeError("collector unavailable")

    assert export_without_breaking_evaluation(BrokenExporter(), []) is False
