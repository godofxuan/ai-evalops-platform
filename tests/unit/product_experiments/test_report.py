from __future__ import annotations

import hashlib

import pytest

from app.product_experiments.report import render_experiment_html


def test_public_v1_renderer_preserves_published_checkpoint_bytes() -> None:
    # Golden digest measured from 8cbad06f32f9a0e010c35da7aa97e68b08007e2f.
    payload = {
        "schema_version": "evalops.public-experiment-summary/1.0",
        "experiment_id": "public-" + "a" * 64,
        "status": "DEMO_PASS",
        "scope": "DEMO",
        "task_type": "QA",
        "case_count": 120,
        "dataset_sha256": "d" * 64,
        "evalops_sha": "e" * 40,
    }
    digest = hashlib.sha256(render_experiment_html(payload).encode("utf-8")).hexdigest()
    assert digest == "7eccb73f817d249b793452fecee1ab7a52b51d6d5e7b2ebf37b0bce402bde130"


def test_report_shows_descriptive_coverage_without_relabeling_the_gate() -> None:
    rendered = render_experiment_html(
        {
            "status": "INSUFFICIENT_EVIDENCE",
            "scope": "DEMO",
            "metric_diagnostics": {
                "cost_usd": {
                    "decision_scope": "DESCRIPTIVE_ONLY",
                    "valid_pair_count": 0,
                    "missing_pair_count": 120,
                }
            },
        }
    )
    assert "DESCRIPTIVE_ONLY" in rendered and "missing_pair_count" in rendered
    assert "INSUFFICIENT_EVIDENCE" in rendered


@pytest.mark.parametrize(
    "status,tone",
    [
        ("DEMO_FAIL", "failure"),
        ("EXECUTION_FAILED", "failure"),
        ("INPUT_REQUIRED", "pending"),
        ("UNKNOWN", "pending"),
        ("DEMO_PASS", "success"),
    ],
)
def test_report_status_style_does_not_color_failures_as_success(status: str, tone: str) -> None:
    rendered = render_experiment_html({"status": status, "scope": "DEMO"})
    assert f'class="status {tone}"' in rendered


def test_v2_report_distinguishes_recall_precision_and_unavailable_values() -> None:
    rendered = render_experiment_html(
        {
            "schema_version": "evalops.experiment-result/2.0",
            "scope": "DEMO",
            "case_comparisons": [
                {
                    "case_id": "q",
                    "baseline_citation_recall": 1.0,
                    "candidate_citation_recall": 1.0,
                    "baseline_citation_precision": 1.0,
                    "candidate_citation_precision": 0.5,
                    "baseline_cost_usd": None,
                    "candidate_cost_usd": 0.0,
                }
            ],
        }
    )
    assert "Citation recall" in rendered and "Citation precision" in rendered
    assert "未提供/不适用 → 0.0 USD" in rendered
    assert "None →" not in rendered


def test_report_escapes_untrusted_case_content_and_explains_demo_boundary() -> None:
    result = {
        "schema_version": "evalops.experiment-result/1.0",
        "experiment_id": "demo",
        "status": "DEMO_PASS",
        "scope": "DEMO",
        "case_count": 1,
        "source_identities": {},
        "dataset_sha256": "d" * 64,
        "evalops_sha": "e" * 40,
        "human_review_status": "PENDING",
        "formal_quality_claim_allowed": False,
        "production_ready": False,
        "automated_assessment": {"status": "PASS", "metrics": {}},
        "case_comparisons": [
            {
                "case_id": "case-1",
                "category": "basic",
                "baseline_answer": "<script>alert(1)</script>",
                "candidate_answer": "safe",
                "baseline_task_success": 0.0,
                "candidate_task_success": 1.0,
                "task_success_delta": 0.0,
                "baseline_citation_correctness": 0.0,
                "candidate_citation_correctness": 1.0,
                "baseline_tool_error_rate": 0.0,
                "candidate_tool_error_rate": 0.0,
                "baseline_latency_ms": 10.0,
                "candidate_latency_ms": 11.0,
                "latency_delta_ms": 1.0,
                "baseline_cost_usd": 0.01,
                "candidate_cost_usd": 0.01,
                "cost_delta_usd": 0.0,
                "baseline_trace_id": "trace-b",
                "candidate_trace_id": "trace-c",
            }
        ],
        "input_requirements": [],
    }

    rendered = render_experiment_html(result)

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "演示通过不等于正式质量提升" in rendered
    assert "trace-b / trace-c" in rendered


def test_agent_report_escapes_tool_trace_and_renders_agent_metrics() -> None:
    rendered = render_experiment_html(
        {
            "experiment_id": "agent-demo",
            "task_type": "AGENT_TOOL_USE",
            "status": "DEMO_PASS",
            "scope": "DEMO",
            "case_count": 1,
            "case_comparisons": [
                {
                    "case_id": "agent-1",
                    "category": "authorization",
                    "baseline_answer": "done",
                    "candidate_answer": "done",
                    "baseline_task_success": 1,
                    "candidate_task_success": 1,
                    "baseline_citation_correctness": 1,
                    "candidate_citation_correctness": 1,
                    "baseline_tool_error_rate": 0,
                    "candidate_tool_error_rate": 0,
                    "baseline_latency_ms": 1,
                    "candidate_latency_ms": 1,
                    "baseline_cost_usd": 0,
                    "candidate_cost_usd": 0,
                    "baseline_trace_id": "b",
                    "candidate_trace_id": "c",
                    "baseline_tool_calls": [
                        {"name": "<script>", "arguments": {}, "status": "success"}
                    ],
                    "candidate_tool_calls": [],
                    "baseline_agent_metrics": {"policy_violation_rate": 1.0},
                    "candidate_agent_metrics": {"policy_violation_rate": 0.0},
                }
            ],
            "automated_assessment": {},
            "input_requirements": [],
        }
    )

    assert "Agent tool-use trace" in rendered
    assert "&lt;script&gt;" in rendered
    assert "policy_violation_rate" in rendered
    assert "<script>" not in rendered
